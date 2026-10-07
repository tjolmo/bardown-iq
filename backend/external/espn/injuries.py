"""League-wide injury report from ESPN.

    https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries

One request returns every team with a listing (teams without injuries are left out): `injuries: [{id, displayName,
injuries: [...]}]`. Each entry has
  * `status`: "Injured Reserve" | "Out" | "Day-To-Day" (also as `type.name`: INJURY_STATUS_IR / _OUT / _DAYTODAY);
  * `details.fantasyStatus.abbreviation`: finer grain, "IR" | "IR-NR" (non-roster) | "IR-LT" (long-term IR) |
    "OUT" | "Day-To-Day";
  * `details.type`: body part, or "Suspension" / "Contract Dispute" / "Personal" (suspensions are listed as IR-NR);
  * `details.returnDate`: ESPN's estimate (often just the next few days for every listing, so not used to decide);
  * `date`: when the entry was last updated (news blurb time, UTC), not when the injury happened;
  * `athlete`: names, `position.abbreviation`, `team.abbreviation`, `status.type` ("active" | "minors" | "injured"
    | "inactive"). The ESPN athlete id is only in its links (".../player/_/id/4565270") and uid ("a:4565270").
Resolved injuries disappear: the per-athlete history (sports.core.api.espn.com/.../seasons/YYYY/athletes/ID/injuries)
keeps only the current season's open entries, and game summaries show today's report, so there is no back history;
the injury snapshots stored from this feed are the only record of what was known before a game.
"""
from __future__ import annotations

import datetime
import re

from external.espn.odds import to_nhl_code
from external.espn.player_ids import PlayerIndex, name_candidates
from external.http import get_with_retries

INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries"

# statuses that keep a player out of tonight's lineup; "day_to_day" players are kept (most of them play)
OUT_STATUSES = {"out", "ir", "ltir", "suspended"}

_FANTASY_STATUS = {"IR": "ir", "IR-NR": "ir", "IR-LT": "ltir", "OUT": "out", "DAY-TO-DAY": "day_to_day"}
_TYPE_STATUS = {"INJURY_STATUS_IR": "ir", "INJURY_STATUS_OUT": "out", "INJURY_STATUS_DAYTODAY": "day_to_day",
                "INJURY_STATUS_SUSPENSION": "suspended"}
_ATHLETE_ID = re.compile(r"(?:/id/|~a:)(\d+)")


def normalize_status(entry: dict) -> str:
    """'suspended' | 'ltir' | 'ir' | 'out' | 'day_to_day' (or ESPN's own status, lowercased, if unknown)."""
    details = entry.get("details") or {}
    if str(details.get("type") or "").lower() == "suspension":
        return "suspended"
    fantasy = ((details.get("fantasyStatus") or {}).get("abbreviation") or "").upper()
    if fantasy in _FANTASY_STATUS:
        return _FANTASY_STATUS[fantasy]
    by_type = _TYPE_STATUS.get(((entry.get("type") or {}).get("name") or "").upper())
    if by_type:
        return by_type
    status = (entry.get("status") or "").lower()
    return {"injured reserve": "ir", "day-to-day": "day_to_day"}.get(status, status.replace(" ", "_") or "unknown")


def _athlete_id(athlete: dict) -> int | None:
    if str(athlete.get("id") or "").isdigit():
        return int(athlete["id"])
    for text in [athlete.get("uid")] + [link.get("href") for link in athlete.get("links") or []] + [
            (athlete.get("headshot") or {}).get("href")]:
        m = _ATHLETE_ID.search(text or "")
        if m:
            return int(m.group(1))
    return None


def _utc(value: str | None) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def _date(value: str | None) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


def parse_injuries(payload: dict | None) -> list[dict]:
    """One dict per listed player: espn_athlete_id, full_name, first_name, last_name, position (ESPN abbreviation),
    team (NHL tri code, None if unknown), status (normalize_status), espn_status, fantasy_status, injury_type,
    roster_status (ESPN athlete status: active / minors / ...), report_date (UTC datetime), return_date (date),
    espn_injury_id, comment (ESPN's short comment)."""
    out = []
    for team in (payload or {}).get("injuries") or []:
        for entry in team.get("injuries") or []:
            athlete = entry.get("athlete") or {}
            details = entry.get("details") or {}
            athlete_id = _athlete_id(athlete)
            if athlete_id is None:
                continue
            out.append({
                "espn_athlete_id": athlete_id,
                "full_name": athlete.get("displayName") or athlete.get("fullName"),
                "first_name": athlete.get("firstName"), "last_name": athlete.get("lastName"),
                "position": (athlete.get("position") or {}).get("abbreviation"),
                "team": to_nhl_code((athlete.get("team") or {}).get("abbreviation")),
                "status": normalize_status(entry),
                "espn_status": entry.get("status"),
                "fantasy_status": (details.get("fantasyStatus") or {}).get("abbreviation"),
                "injury_type": details.get("type"),
                "roster_status": (athlete.get("status") or {}).get("type"),
                "report_date": _utc(entry.get("date")),
                "return_date": _date(details.get("returnDate")),
                "espn_injury_id": int(entry["id"]) if str(entry.get("id") or "").isdigit() else None,
                "comment": (entry.get("shortComment") or "")[:500] or None,
            })
    return out


async def fetch_injuries() -> list[dict] | None:
    """Today's league-wide injury report, or None when ESPN can't be reached (callers keep the last snapshot)."""
    try:
        response = await get_with_retries(INJURIES_URL)
        response.raise_for_status()
        payload = response.json()
    except Exception as e:
        print(f"Error fetching ESPN injuries: {e!r}")
        return None
    if not isinstance(payload, dict) or "injuries" not in payload:
        print(f"ESPN injuries: unexpected payload (keys {list(payload)[:5] if isinstance(payload, dict) else type(payload)})")
        return None
    return parse_injuries(payload)


def match_injured_player(idx: PlayerIndex, row: dict, known: dict[int, int] | None = None) -> tuple[int | None, str]:
    """(NHL player id or None, how). ESPN ids already paired with NHL ids (player_prop_odds) are trusted; otherwise
    the name (exact, then same last name with a compatible first name) with goalie/skater agreeing, preferring the
    player whose current team is the listed team, else the only such player in the league."""
    if known and row["espn_athlete_id"] in known:
        return known[row["espn_athlete_id"]], "known"
    goalie = (row.get("position") or "").upper() == "G" if row.get("position") else None
    candidates, how = name_candidates(idx, row, goalie)
    if not candidates:
        return None, "name_not_found"
    on_team = [c for c in candidates if row.get("team") and idx.players[c].get("current_team") == row["team"]]
    if len(on_team) == 1:
        return on_team[0], f"{how}_team"
    if len(on_team) > 1:
        return None, f"{how}_ambiguous"
    if len(candidates) == 1 and how == "exact":
        return candidates[0], "exact_other_team"   # traded / waived since ESPN last updated the team
    return None, f"{how}_no_team"


def match_injured_players(idx: PlayerIndex, rows: list[dict], known: dict[int, int] | None = None) -> tuple[list[dict], dict]:
    """`rows` with player_id set (None when unmatched), plus {full_name: reason} for the unmatched."""
    out, unmatched = [], {}
    for row in rows:
        pid, how = match_injured_player(idx, row, known)
        out.append({**row, "player_id": pid})
        if pid is None:
            unmatched[row.get("full_name") or str(row["espn_athlete_id"])] = how
    return out, unmatched
