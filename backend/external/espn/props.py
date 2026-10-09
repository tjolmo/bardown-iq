"""NHL player-prop odds from ESPN's core API (Feb 2024 onward).

Endpoints
---------
Event ids come from the scoreboard (see external.espn.odds). Per event:

    {CORE}/events/{id}/competitions/{id}/odds            (same payload/cache as game odds)
      -> each provider item that carries prop bets has a
         `propBets: {"$ref": ".../odds/{provider_id}/propBets"}` link.
    {CORE}/events/{id}/competitions/{id}/odds/{provider_id}/propBets?limit=1000
      -> every prop row in ONE page (default page size is 25; `limit` collapses
         the ~10-25 pages to one). Games without props return HTTP 404
         ("No propBets found ...").

What ESPN has (probed Oct 2026)
-------------------------------
* Oct 2023 - Jan 2024: no props for any game (404 for every provider).
* Feb 2024 - early Dec 2025: provider 58 "ESPN BET" (plus 59 "ESPN Bet - Live Odds",
  an in-game duplicate we skip). Rows are LABELLED: `current` / `open` hold an
  `over` or `under` block next to `target` (the line).
* Dec 2025 onward: provider 100 "Draft Kings", but only for a minority of
  regular-season games until ~Apr 2026 (most games 404). Rows are NOT labelled:
  `current` / `open` contain only `target`; the price is in `odds.american.value`
  / `.open`. The two sides of a market are consecutive rows for the same athlete,
  type and target, OVER FIRST (see `assign_unlabelled_sides` for the evidence).
  Each row keeps its side when the line moves: `open.target` can differ from
  `current.target` (e.g. SOG opened 2.5, now 3.5) and is stored separately.
* Player props appear on the day of the game (upcoming games carry only team/game
  props), so a pre-game snapshot needs a same-day fetch. For finished games
  `current` is the last price ESPN stored before puck drop (`lastUpdated` is
  usually hours before the start, i.e. "latest pre-game", not a true close).

Row shape (one per player market)
---------------------------------
prop_type slugs:
* two-sided over/under: points, assists, goals, shots_on_goal, pp_points,
  blocked_shots, saves, hits
* one-sided "yes" prices (under_price is always NULL):
  anytime_goal, first_goal, last_goal, first_team_goal (all stored at line 0.5),
  *_milestone (DraftKings ladders "N+" and "To Score N+ Goals"), stored with
  line = N - 0.5 so the yes price lines up with the over of an O/U at that line.
Team / game props (period lines, team totals, BTTS...) and ESPN BET's catch-all
"Hockey Player Prop" (mixed, unlabelled markets) are skipped.
"""

from __future__ import annotations

import collections
import datetime as dt
import logging
from typing import Any, Iterable

from external.espn.odds import CORE_BASE, DEAD_STATUSES, EspnClient, parse_american, parse_line

logger = logging.getLogger(__name__)

# ESPN type name -> (slug, kind). kind: "ou" two-sided over/under, "yes" one-sided,
# "milestone" one-sided "N+" ladder (line = N - 0.5).
PROP_TYPES: dict[str, tuple[str, str]] = {
    "Total Points": ("points", "ou"),
    "Total Assists": ("assists", "ou"),
    "Total Goals": ("goals", "ou"),
    "Total Shots on Goal": ("shots_on_goal", "ou"),
    "Total Power Play Points": ("pp_points", "ou"),
    "Total Blocked Shots": ("blocked_shots", "ou"),
    "Total Saves": ("saves", "ou"),
    "Total Hits": ("hits", "ou"),
    "Anytime Goalscorer": ("anytime_goal", "yes"),
    "First Goalscorer": ("first_goal", "yes"),
    "Last Goalscorer": ("last_goal", "yes"),
    "First Team Goalscorer": ("first_team_goal", "yes"),
    "To Score 2+ Goals": ("goals_milestone", "yes"),
    "To Score 3+ Goals": ("goals_milestone", "yes"),
    "Points Milestones": ("points_milestone", "milestone"),
    "Assists Milestones": ("assists_milestone", "milestone"),
    "Goals Milestones": ("goals_milestone", "milestone"),
    "Shots on Goal Milestones": ("shots_on_goal_milestone", "milestone"),
    "Blocked Shots Milestones": ("blocked_shots_milestone", "milestone"),
    "Goalkeeper Saves Milestones": ("saves_milestone", "milestone"),
    "Powerplay Points Milestones": ("pp_points_milestone", "milestone"),
}
# fixed lines for one-sided markets that carry no target
YES_LINES = {"Anytime Goalscorer": 0.5, "First Goalscorer": 0.5, "Last Goalscorer": 0.5,
             "First Team Goalscorer": 0.5, "To Score 2+ Goals": 1.5, "To Score 3+ Goals": 2.5}
GOALIE_PROP_TYPES = {"saves", "saves_milestone"}
LIVE_PROVIDER_IDS = {"59"}


def _ref_id(obj: Any, marker: str) -> str | None:
    """'.../athletes/3114766?lang=en' -> '3114766'."""
    ref = obj.get("$ref") if isinstance(obj, dict) else None
    if not ref or marker not in ref:
        return None
    return ref.split(marker, 1)[1].split("?", 1)[0].split("/", 1)[0]


def prop_providers(odds_payload: dict | None) -> list[tuple[str, str]]:
    """(provider_id, provider_name) of the pre-game providers whose odds item links to propBets."""
    out = []
    for item in (odds_payload or {}).get("items") or []:
        ref = (item.get("propBets") or {}).get("$ref")
        provider = item.get("provider") or {}
        pid = str(provider.get("id") or "")
        name = provider.get("name") or pid
        if ref and pid not in LIVE_PROVIDER_IDS and "live" not in name.lower():
            out.append((pid, name))
    return out


def _target(block: Any) -> float | None:
    t = block.get("target") if isinstance(block, dict) else None
    if not isinstance(t, dict):
        return None
    value = t.get("value")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else parse_line(value)


def _label(block: Any) -> str | None:
    if not isinstance(block, dict):
        return None
    if "over" in block:
        return "over"
    if "under" in block:
        return "under"
    return None


def _parse_ts(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_prop_rows(payload: dict | None) -> list[dict]:
    """Flattens propBets items into one dict per row (one side of one market).
    Rows without an athlete (team/game props) and unknown types are dropped."""
    rows = []
    for idx, item in enumerate((payload or {}).get("items") or []):
        athlete_id = _ref_id(item.get("athlete"), "/athletes/")
        type_name = (item.get("type") or {}).get("name")
        if not athlete_id or type_name not in PROP_TYPES:
            continue
        slug, kind = PROP_TYPES[type_name]
        odds = item.get("odds") or {}
        american = odds.get("american") or {}
        current, opened = item.get("current") or {}, item.get("open") or {}
        rows.append({
            "idx": idx,
            "espn_athlete_id": int(athlete_id),
            "espn_type": type_name,
            "prop_type": slug,
            "kind": kind,
            "price": parse_american(american.get("value")),
            "open_price": parse_american(american.get("open")),
            "target": _target(current) if _target(current) is not None else parse_line((odds.get("total") or {}).get("value")),
            "open_target": _target(opened) if _target(opened) is not None else parse_line((odds.get("total") or {}).get("open")),
            "side": _label(current),
            "open_side": _label(opened),
            "last_updated": _parse_ts(item.get("lastUpdated")),
        })
    return rows


def assign_unlabelled_sides(rows: list[dict]) -> None:
    """DraftKings rows carry no over/under label. Within each (athlete, type,
    current target) group, rows come in consecutive pairs listed OVER then UNDER;
    sides are set in place and `sides_inferred` marks them.

    Evidence (2025-26 DK games, see the backfill report): on markets where DK also
    posts a one-sided ladder for the same event (Points/Assists/SOG milestone "N+",
    Anytime Goalscorer vs Total Goals), the first row's price is the one matching
    the "N+" yes price; and on 0.5-line assists/PP points the first row is the
    plus-money side for most skaters, as an over must be. A group with an odd
    number of rows leaves the trailing row unassigned (dropped)."""
    groups: dict[tuple, list[dict]] = collections.defaultdict(list)
    for r in rows:
        if r["kind"] == "ou" and r["side"] is None:
            groups[(r["espn_athlete_id"], r["espn_type"], r["target"])].append(r)
    for group in groups.values():
        group.sort(key=lambda r: r["idx"])
        for i, r in enumerate(group):
            if i % 2 == 0 and i + 1 == len(group):
                break  # unpaired trailing row: side unknown
            r["side"] = "over" if i % 2 == 0 else "under"
            r["sides_inferred"] = True


def build_markets(rows: list[dict]) -> list[dict]:
    """Collapses side rows into one market dict per (athlete, prop_type, line)."""
    assign_unlabelled_sides(rows)
    markets: dict[tuple, dict] = {}
    for r in sorted(rows, key=lambda r: r["idx"]):
        kind = r["kind"]
        if kind == "ou":
            if r["side"] is None or r["target"] is None:
                continue
            line, side = r["target"], r["side"]
            open_line = r["open_target"]
            open_side = r["open_side"] or side  # a row keeps its side when the line moves
        elif kind == "milestone":
            if r["target"] is None:
                continue
            line, side = r["target"] - 0.5, "over"
            open_line = None if r["open_target"] is None else r["open_target"] - 0.5
            open_side = "over"
        else:  # yes
            line, side = YES_LINES[r["espn_type"]], "over"
            open_line, open_side = line, "over"
        key = (r["espn_athlete_id"], r["prop_type"], line)
        m = markets.get(key)
        if m is None:
            m = markets[key] = {
                "espn_athlete_id": r["espn_athlete_id"], "prop_type": r["prop_type"], "line": line,
                "over_price": None, "under_price": None, "open_line": None,
                "open_over_price": None, "open_under_price": None,
                "sides_inferred": bool(r.get("sides_inferred")), "last_updated": None,
                "_sources": set(),
            }
        if (r["espn_type"], side) in m["_sources"] or m[f"{side}_price"] is not None:
            continue  # duplicate (e.g. "To Score 2+ Goals" and "Goals Milestones" 2+): keep the first
        m["_sources"].add((r["espn_type"], side))
        m[f"{side}_price"] = r["price"]
        if r["open_price"] is not None and open_line is not None:
            if m["open_line"] is None:
                m["open_line"] = open_line
            if m["open_line"] == open_line:  # never mix prices from two different opening lines
                m[f"open_{open_side}_price"] = r["open_price"]
        if r["last_updated"] and (m["last_updated"] is None or r["last_updated"] > m["last_updated"]):
            m["last_updated"] = r["last_updated"]
    out = []
    for m in markets.values():
        m.pop("_sources")
        if m["over_price"] is None and m["under_price"] is None:
            continue
        out.append(m)
    return out


def parse_prop_bets(payload: dict | None) -> list[dict]:
    """propBets payload -> market dicts (see build_markets)."""
    return build_markets(parse_prop_rows(payload))


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def odds_payload(client: EspnClient, event_id: str, cache: bool) -> dict | None:
    """Raw odds collection for an event, sharing EspnClient.odds' cache entry."""
    url = f"{CORE_BASE}/events/{event_id}/competitions/{event_id}/odds"
    return client.cached_get("odds", event_id, url, {"limit": 100}, cache=cache)


def prop_bets_payload(client: EspnClient, event_id: str, provider_id: str, cache: bool) -> dict | None:
    url = f"{CORE_BASE}/events/{event_id}/competitions/{event_id}/odds/{provider_id}/propBets"
    return client.cached_get("props", f"{event_id}_{provider_id}", url, {"limit": 1000}, cache=cache)


def athlete_payload(client: EspnClient, athlete_id: int) -> dict | None:
    """ESPN athlete bio (name, position, birth date, jersey); cached permanently."""
    url = f"{CORE_BASE}/athletes/{athlete_id}"
    return client.cached_get("athletes", str(athlete_id), url, None, cache=True)


def parse_athlete(payload: dict | None) -> dict | None:
    if not payload or payload.get("_status") == 404 or not payload.get("id"):
        return None
    position = payload.get("position") or {}
    return {
        "espn_athlete_id": int(payload["id"]),
        "first_name": payload.get("firstName") or "",
        "last_name": payload.get("lastName") or "",
        "full_name": payload.get("fullName") or payload.get("displayName") or "",
        "position": position.get("abbreviation"),
        "birth_date": (payload.get("dateOfBirth") or "")[:10] or None,
        "jersey": payload.get("jersey"),
    }


def _event_final(event: dict) -> bool:
    return bool(event.get("completed")) or event.get("status") in DEAD_STATUSES


def fetch_event_markets(client: EspnClient, event: dict) -> tuple[list[dict], dict]:
    """(markets with `book` set, stats) for one scoreboard event."""
    final = _event_final(event)
    stats = collections.Counter()
    odds = odds_payload(client, event["espn_event_id"], cache=final)
    if odds is None:
        stats["odds_failed"] += 1
        return [], stats
    markets = []
    for provider_id, name in prop_providers(odds):
        payload = prop_bets_payload(client, event["espn_event_id"], provider_id, cache=final)
        if payload is None:
            stats["props_failed"] += 1
            continue
        items = payload.get("items") or []
        stats["prop_rows_raw"] += len(items)
        for it in items:
            if it.get("athlete") and (it.get("type") or {}).get("name") not in PROP_TYPES:
                stats[f"skipped_type:{(it.get('type') or {}).get('name')}"] += 1
        for m in parse_prop_bets(payload):
            m["book"] = name
            markets.append(m)
    stats["events_with_props"] += 1 if markets else 0
    return markets, stats


def fetch_markets(client: EspnClient, events: list[dict]) -> tuple[dict[str, list[dict]], collections.Counter]:
    """event_id -> markets for every event, in chunks so progress is logged."""
    out: dict[str, list[dict]] = {}
    totals: collections.Counter = collections.Counter()
    for i in range(0, len(events), 200):
        chunk = events[i:i + 200]
        for e, (markets, stats) in zip(chunk, client.map(lambda e: fetch_event_markets(client, e), chunk)):
            out[e["espn_event_id"]] = markets
            totals.update(stats)
        logger.info("props %d/%d (through %s), network fetches so far %d",
                    min(i + 200, len(events)), len(events), chunk[-1]["date"], client.fetched)
    return out, totals


def fetch_athletes(client: EspnClient, athlete_ids: Iterable[int]) -> dict[int, dict]:
    ids = sorted(set(athlete_ids))
    infos = client.map(lambda a: parse_athlete(athlete_payload(client, a)), ids)
    return {a: info for a, info in zip(ids, infos) if info}


# ---------------------------------------------------------------------------
# Matching to NHL games / players
# ---------------------------------------------------------------------------

def build_player_prop_rows(events: list[dict], markets_by_event: dict[str, list[dict]], nhl_games: list[dict],
                           mapping: dict[int, int]) -> tuple[list[dict], collections.Counter]:
    """player_prop_odds rows for markets whose event matched an NHL game (events must already
    have `nhl_game_id`, see external.espn.odds.match_nhl_ids) and whose athlete is in `mapping`."""
    stats: collections.Counter = collections.Counter()
    rows = []
    for e in events:
        markets = markets_by_event.get(e["espn_event_id"]) or []
        if not markets:
            continue
        if not e.get("nhl_game_id"):
            stats["markets_unmatched_game"] += len(markets)
            continue
        for m in markets:
            pid = mapping.get(m["espn_athlete_id"])
            if pid is None:
                stats["markets_unmatched_player"] += 1
                continue
            stats["markets_stored"] += 1
            rows.append({
                "game_id": int(e["nhl_game_id"]), "player_id": pid, "prop_type": m["prop_type"],
                "line": m["line"], "book": m["book"], "espn_athlete_id": m["espn_athlete_id"],
                "espn_event_id": int(e["espn_event_id"]), "over_price": m["over_price"],
                "under_price": m["under_price"], "open_line": m["open_line"],
                "open_over_price": m["open_over_price"], "open_under_price": m["open_under_price"],
                "sides_inferred": m["sides_inferred"], "espn_last_updated": m["last_updated"],
            })
    return rows, stats


def athlete_contexts(events: list[dict], markets_by_event: dict[str, list[dict]],
                     nhl_games: list[dict]) -> tuple[dict[int, list[tuple[int, str, str]]], dict[int, bool]]:
    """athlete -> [(nhl game id, home, away)] for matched events, and athlete -> is goalie
    (True if he only ever had saves markets) as a fallback position hint."""
    teams = {int(g["id"]): (g["home_team_tri_code"], g["away_team_tri_code"]) for g in nhl_games}
    contexts: dict[int, list] = collections.defaultdict(list)
    kinds: dict[int, set] = collections.defaultdict(set)
    for e in events:
        gid = e.get("nhl_game_id")
        if not gid:
            continue
        gid = int(gid)
        for a in {m["espn_athlete_id"] for m in markets_by_event.get(e["espn_event_id"]) or []}:
            contexts[a].append((gid, *teams[gid]))
        for m in markets_by_event.get(e["espn_event_id"]) or []:
            kinds[m["espn_athlete_id"]].add(m["prop_type"] in GOALIE_PROP_TYPES)
    hints = {a: k == {True} for a, k in kinds.items()}
    return dict(contexts), hints


def fetch_player_prop_odds(start: dt.date, end: dt.date, nhl_games: list[dict], player_index,
                           known: dict[int, int] | None = None, cache_dir: str | None = None,
                           workers: int = 4) -> tuple[list[dict], dict]:
    """Blocking: scoreboards -> odds -> propBets -> athletes for start..end (inclusive),
    matched to `nhl_games` and to NHL players through `player_index`
    (external.espn.player_ids.build_player_index). Returns (rows, report)."""
    import tempfile

    from external.espn.odds import fetch_events, match_nhl_ids
    from external.espn.player_ids import resolve_athletes

    if cache_dir is None:
        with tempfile.TemporaryDirectory(prefix="espn_props_") as tmp:
            return fetch_player_prop_odds(start, end, nhl_games, player_index, known, tmp, workers)
    client = EspnClient(cache_dir, workers=workers)
    events = [e for e in fetch_events(client, start, end) if e["season_type"] != "preseason"]
    markets_by_event, stats = fetch_markets(client, events)
    match_nhl_ids(events, nhl_games)
    contexts, hints = athlete_contexts(events, markets_by_event, nhl_games)
    athletes = fetch_athletes(client, [a for a in contexts if a not in (known or {})])
    mapping, unmatched = resolve_athletes(player_index, athletes, contexts, hints, known)
    rows, row_stats = build_player_prop_rows(events, markets_by_event, nhl_games, mapping)
    stats.update(row_stats)
    report = {
        "stats": stats,
        "athletes": len(contexts),
        "athletes_matched": sum(1 for a in contexts if a in mapping),
        "unmatched": {a: (unmatched[a], athletes.get(a, {}).get("full_name")) for a in unmatched},
        "network_fetches": client.fetched,
        "events": len(events),
    }
    logger.info("player props %s..%s: %d events, %d with props, %d rows, athletes %d/%d matched, %d network fetches",
                start, end, len(events), stats["events_with_props"], len(rows),
                report["athletes_matched"], report["athletes"], client.fetched)
    return rows, report
