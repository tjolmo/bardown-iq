"""Historical NHL moneylines / totals from ESPN's undocumented APIs.

Endpoints
---------
Scoreboard (event ids for one *local* game date, 1 request per day):
    https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates=YYYYMMDD
  `dates` is the North-American local game date (what the NHL calls gameDate); the
  event's `date` field is the UTC start time, so a 7pm ET game shows up as the next
  day in UTC. We key every event by the queried date, which lines up with NHL dates.

Odds (every book ESPN carries for one event, 1 request per event):
    https://sports.core.api.espn.com/v2/sports/hockey/leagues/nhl/events/{id}/competitions/{id}/odds
  Each item is one provider: `provider.{id,name}`, `homeTeamOdds` / `awayTeamOdds`
  (`moneyLine` plus `current` / `open` / `close` blocks holding
  `{moneyLine,spread,pointSpread}.american` strings), `overUnder`, `overOdds`,
  `underOdds`, and item-level `current` / `open` / `close` blocks for the total.
  `$ref` links point at the provider (`.../providers/{id}`), the per-provider odds
  (`.../odds/{provider_id}`) and season-scoped teams (`.../seasons/{y}/teams/{id}`);
  we never need to follow them because everything we use is inlined.

What we found per era (see report / tests for details)
------------------------------------------------------
* before ~May 2019: the odds collection is empty for NHL events (count 0); the
  consensus movement feed (provider 1002) is empty for NHL in every era.
* mid 2019 .. 2022-23: 6-12 books, values frozen at puck drop (= closing). Several
  books (Bet365, DraftKings id 40, Unibet, SugarHouse, Titanbets, Holland Casino,
  BetfairSportsbook, Betradar...) frequently carry *3-way regulation* prices or junk
  (e.g. +145 / +145) in the moneyline slot, so every row is screened by its
  overround: a genuine 2-way moneyline pair sums to roughly 1.00-1.12 implied prob,
  a 3-way regulation pair to ~0.80-0.90. No `open` blocks; some rows carry a
  backfilled `close` block identical to `current`.
* 2023-24: same books plus real per-book `open` / `close` snapshots.
* 2024-25: only "ESPN BET" (id 58) plus "ESPN Bet - Live Odds" (id 59, in-game,
  must be dropped). 2025-26 onward: only "Draft Kings" (id 100), with open/close.

Closing consensus
-----------------
No single book spans every era (Caesars 2019-24, ESPN BET 2022-25, Draft Kings id 100
from 2025-26), so the per-game consensus is the **median vig-free home win
probability across all valid 2-way pre-game books** (live feeds excluded, overround
screen above). For 2024-25 and later that is simply the one book ESPN carries.
`consensus_home_ml` / `consensus_away_ml` are the medians of the valid books' prices
and `n_books` / `books` show what went into it.

CLI
---
    python -m external.espn.odds --start 2015-10-01 --end 2026-10-06 \
        --out /scratch/odds/nhl_moneylines.csv [--games-csv games.csv]

Raw JSON is cached under --cache-dir (default: next to --out, `espn_cache/`), so
reruns only fetch what is missing. Requests use a descriptive User-Agent, at most
--workers (default 4) in flight, and exponential backoff on 429/5xx/timeouts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard"
CORE_BASE = "https://sports.core.api.espn.com/v2/sports/hockey/leagues/nhl"
USER_AGENT = "nhl-prediction-capstone/1.0 (personal research; historical odds backfill)"
RETRY_STATUSES = {429, 500, 502, 503, 504}

# 2-way moneyline pairs sum to ~1.02-1.08 implied probability; 3-way regulation
# prices (which several legacy books put in the moneyline slot) sum to ~0.8-0.9.
MIN_OVERROUND = 0.98
MAX_OVERROUND = 1.15

# ESPN abbreviation -> NHL tri code (only the ones that differ, plus aliases seen
# in older data). Anything not listed is assumed identical.
ESPN_TO_NHL = {
    "NJ": "NJD",
    "SJ": "SJS",
    "TB": "TBL",
    "LA": "LAK",
    "UTAH": "UTA",
    "UTA": "UTA",
    "VEG": "VGK",
    "VGS": "VGK",
    "PHX": "ARI",  # Coyotes were PHX until 2014; NHL ids from 2014-15 use ARI
    "WAS": "WSH",
    "MON": "MTL",
    "CLB": "CBJ",
    "NAS": "NSH",
    "CAL": "CGY",
    "WIN": "WPG",
}
NHL_TRI_CODES = {
    "ANA", "ARI", "BOS", "BUF", "CAR", "CBJ", "CGY", "CHI", "COL", "DAL", "DET",
    "EDM", "FLA", "LAK", "MIN", "MTL", "NJD", "NSH", "NYI", "NYR", "OTT", "PHI",
    "PIT", "SEA", "SJS", "STL", "TBL", "TOR", "UTA", "VAN", "VGK", "WPG", "WSH",
}

DEAD_STATUSES = {"STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_CANCELLED", "STATUS_SUSPENDED"}

SEASON_TYPES = {1: "preseason", 2: "regular", 3: "postseason", 4: "offseason"}


def to_nhl_code(espn_abbr: str | None) -> str | None:
    """Normalize an ESPN team abbreviation to the NHL tri code (None if unknown,
    e.g. All-Star / exhibition teams)."""
    if not espn_abbr:
        return None
    code = ESPN_TO_NHL.get(espn_abbr.upper(), espn_abbr.upper())
    return code if code in NHL_TRI_CODES else None


# ---------------------------------------------------------------------------
# Odds math
# ---------------------------------------------------------------------------

def parse_american(value: Any) -> float | None:
    """'+145' / '-110' / 145 / 'EVEN' -> float; 0, '', junk -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
    else:
        s = str(value).strip().replace("+", "")
        if s.upper() in ("EVEN", "EV", "PK"):
            return 100.0
        try:
            num = float(s)
        except ValueError:
            return None
    # |price| < 100 is not a valid American price; 0 is ESPN's "missing"
    return num if abs(num) >= 100 else None


def parse_line(value: Any) -> float | None:
    """A point line (total / puck line) such as '6.5' or -1.5; 0 means missing."""
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(str(value).replace("+", "")) if not isinstance(value, (int, float)) else float(value)
    except ValueError:
        return None
    return num if num != 0 else None


def implied_prob(american: float | None) -> float | None:
    if american is None:
        return None
    return 100.0 / (american + 100.0) if american > 0 else -american / (-american + 100.0)


def devig(home_ml: float | None, away_ml: float | None) -> tuple[float | None, float | None, float | None]:
    """Returns (home_prob, away_prob, overround) with the two implied probs normalized
    to sum to 1. All None if either price is missing."""
    ph, pa = implied_prob(home_ml), implied_prob(away_ml)
    if ph is None or pa is None:
        return None, None, None
    total = ph + pa
    return ph / total, pa / total, total


def is_valid_two_way(home_ml: float | None, away_ml: float | None) -> bool:
    _, _, overround = devig(home_ml, away_ml)
    return overround is not None and MIN_OVERROUND <= overround <= MAX_OVERROUND


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _pick(d: Any, *keys: str) -> Any:
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def parse_scoreboard(payload: dict, date: str) -> list[dict]:
    """One dict per event on the scoreboard. `date` is the queried YYYYMMDD local date."""
    events = []
    for event in payload.get("events") or []:
        comp = (event.get("competitions") or [{}])[0]
        status = _pick(comp, "status", "type") or _pick(event, "status", "type") or {}
        season_type = _pick(event, "season", "type")
        row = {
            "date": int(date),
            "espn_event_id": str(event.get("id")),
            "start_utc": event.get("date"),
            "espn_season": _pick(event, "season", "year"),
            "season_type": SEASON_TYPES.get(season_type, season_type),
            "status": status.get("name"),
            "completed": bool(status.get("completed", False)),
        }
        for side in comp.get("competitors") or []:
            prefix = "home" if side.get("homeAway") == "home" else "away"
            abbr = _pick(side, "team", "abbreviation")
            row[f"{prefix}_espn_abbr"] = abbr
            row[f"{prefix}_team"] = to_nhl_code(abbr)
            score = side.get("score")
            try:
                row[f"{prefix}_score"] = int(score) if score not in (None, "") else None
            except (TypeError, ValueError):
                row[f"{prefix}_score"] = None
        events.append(row)
    return events


def _side_ml(side: dict, phase: str) -> float | None:
    return parse_american(_pick(side, phase, "moneyLine", "american"))


def parse_odds(payload: dict) -> list[dict]:
    """One dict per provider for an event's core-API odds collection.

    `home_ml` / `away_ml` are the closing prices: the `close` block when present,
    else `current` (frozen at puck drop for finished games), else the top-level
    `moneyLine`. Open/close snapshot columns are filled only when ESPN has them
    (2023-24 onward in practice)."""
    rows = []
    for item in payload.get("items") or []:
        provider = item.get("provider") or {}
        name = provider.get("name") or ""
        home = item.get("homeTeamOdds") or {}
        away = item.get("awayTeamOdds") or {}

        def closing(side: dict) -> float | None:
            for value in (_side_ml(side, "close"), _side_ml(side, "current"), parse_american(side.get("moneyLine"))):
                if value is not None:
                    return value
            return None

        home_ml, away_ml = closing(home), closing(away)
        total = (parse_line(_pick(item, "close", "total", "american"))
                 or parse_line(_pick(item, "current", "total", "american"))
                 or parse_line(item.get("overUnder")))
        home_p, away_p, overround = devig(home_ml, away_ml)
        valid = overround is not None and MIN_OVERROUND <= overround <= MAX_OVERROUND
        if not valid:  # 3-way regulation prices / junk: keep the raw prices, drop the probs
            home_p = away_p = None
        open_home, open_away = _side_ml(home, "open"), _side_ml(away, "open")
        open_home_p = devig(open_home, open_away)[0] if is_valid_two_way(open_home, open_away) else None
        rows.append({
            "provider_id": str(provider.get("id") or ""),
            "provider": name,
            "is_live": "live" in name.lower(),
            "home_ml": home_ml,
            "away_ml": away_ml,
            "overround": overround,
            "valid_2way": valid,
            "home_prob": home_p,
            "away_prob": away_p,
            "total": total,
            "over_odds": parse_american(_pick(item, "current", "over", "american")) or parse_american(item.get("overOdds")),
            "under_odds": parse_american(_pick(item, "current", "under", "american")) or parse_american(item.get("underOdds")),
            "home_spread": parse_line(_pick(home, "current", "pointSpread", "american")),
            "open_home_ml": open_home,
            "open_away_ml": open_away,
            "open_home_prob": open_home_p,
            "close_home_ml": _side_ml(home, "close"),
            "close_away_ml": _side_ml(away, "close"),
            "open_total": parse_line(_pick(item, "open", "total", "american")),
            "close_total": parse_line(_pick(item, "close", "total", "american")),
        })
    return rows


def _median(values: Iterable[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return statistics.median(vals) if vals else None


def consensus(book_rows: list[dict]) -> dict:
    """Collapse one event's book rows to a closing consensus (see module docstring)."""
    good = [r for r in book_rows if r["valid_2way"] and not r["is_live"]]
    pregame = [r for r in book_rows if not r["is_live"]]
    totals_from = good or pregame
    home_prob = _median(r["home_prob"] for r in good)
    return {
        "n_books_total": len(pregame),
        "n_books": len(good),
        "books": "|".join(sorted(r["provider"] for r in good)),
        "consensus_home_ml": _median(r["home_ml"] for r in good),
        "consensus_away_ml": _median(r["away_ml"] for r in good),
        "home_prob_novig": home_prob,
        "away_prob_novig": None if home_prob is None else 1 - home_prob,
        "overround": _median(r["overround"] for r in good),
        "total_line": _median(r["total"] for r in totals_from),
        "open_home_prob_novig": _median(r["open_home_prob"] for r in good),
        "open_total_line": _median(r["open_total"] for r in totals_from),
    }


# ---------------------------------------------------------------------------
# HTTP with disk cache
# ---------------------------------------------------------------------------

class EspnClient:
    """Polite, cached fetcher. Responses are stored as raw JSON under cache_dir and
    reused on later runs. Callers decide whether a response is final (cacheable)."""

    def __init__(self, cache_dir: str | os.PathLike, workers: int = 4, retries: int = 4, backoff: float = 1.5):
        import requests  # local import: tests of the parsers don't need it

        self._requests = requests
        self.cache_dir = Path(cache_dir)
        self.workers = workers
        self.retries = retries
        self.backoff = backoff
        self._local = threading.local()
        self.fetched = 0

    def _session(self):
        if not hasattr(self._local, "session"):
            s = self._requests.Session()
            s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
            self._local.session = s
        return self._local.session

    def _get(self, url: str, params: dict | None = None) -> dict | None:
        last = None
        for attempt in range(self.retries + 1):
            try:
                resp = self._session().get(url, params=params, timeout=20)
                if resp.status_code == 200:
                    self.fetched += 1
                    return resp.json()
                if resp.status_code == 404:
                    return {"count": 0, "items": [], "_status": 404}
                last = f"HTTP {resp.status_code}"
                if resp.status_code not in RETRY_STATUSES:
                    break
            except (self._requests.RequestException, ValueError) as e:
                last = repr(e)
            time.sleep(self.backoff * 2 ** attempt)
        logger.warning("GET %s %s failed: %s", url, params or "", last)
        return None

    def cached_get(self, kind: str, key: str, url: str, params: dict | None, cache: bool) -> dict | None:
        path = self.cache_dir / kind / f"{key}.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
        payload = self._get(url, params)
        if payload is not None and cache:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(payload, f)
            tmp.replace(path)
        return payload

    def scoreboard(self, date: str) -> list[dict] | None:
        """Events for a YYYYMMDD date. Only dates at least 2 days old are cached."""
        final = dt.datetime.strptime(date, "%Y%m%d").date() <= dt.date.today() - dt.timedelta(days=2)
        payload = self.cached_get("scoreboard", date, SCOREBOARD_URL, {"dates": date, "limit": 100}, cache=final)
        return None if payload is None else parse_scoreboard(payload, date)

    def odds(self, event_id: str, completed: bool) -> list[dict] | None:
        url = f"{CORE_BASE}/events/{event_id}/competitions/{event_id}/odds"
        payload = self.cached_get("odds", event_id, url, {"limit": 100}, cache=completed)
        return None if payload is None else parse_odds(payload)

    def map(self, fn, items: list) -> list:
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            return list(pool.map(fn, items))


def date_range(start: dt.date, end: dt.date) -> list[str]:
    return [(start + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((end - start).days + 1)]


def fetch_events(client: EspnClient, start: dt.date, end: dt.date) -> list[dict]:
    """All scoreboard events between start and end (inclusive)."""
    dates = date_range(start, end)
    events: list[dict] = []
    done = 0
    for i in range(0, len(dates), 60):  # chunks so progress gets logged
        chunk = dates[i:i + 60]
        for date, result in zip(chunk, client.map(client.scoreboard, chunk)):
            if result is None:
                logger.warning("scoreboard %s failed; skipped", date)
                continue
            events.extend(result)
        done += len(chunk)
        logger.info("scoreboards %d/%d (through %s), %d events", done, len(dates), chunk[-1], len(events))
    # ESPN occasionally lists a postponed game on two dates; keep the completed copy
    by_id: dict[str, dict] = {}
    for e in events:
        prev = by_id.get(e["espn_event_id"])
        if prev is None or (e["completed"] and not prev["completed"]):
            by_id[e["espn_event_id"]] = e
    return sorted(by_id.values(), key=lambda e: (e["date"], e["espn_event_id"]))


def fetch_book_rows(client: EspnClient, events: list[dict]) -> dict[str, list[dict] | None]:
    """event_id -> parsed book rows (None if the request failed)."""
    out: dict[str, list[dict] | None] = {}
    for i in range(0, len(events), 200):
        chunk = events[i:i + 200]
        # finished (or postponed/canceled) events never change, so their odds get cached
        results = client.map(lambda e: client.odds(e["espn_event_id"], e["completed"] or e.get("status") in DEAD_STATUSES), chunk)
        for e, rows in zip(chunk, results):
            out[e["espn_event_id"]] = rows
        logger.info("odds %d/%d (through %s), network fetches so far %d",
                    min(i + 200, len(events)), len(events), chunk[-1]["date"], client.fetched)
    return out


# ---------------------------------------------------------------------------
# Matching to NHL game ids
# ---------------------------------------------------------------------------

def _shift_date(yyyymmdd: int, days: int) -> int:
    d = dt.datetime.strptime(str(yyyymmdd), "%Y%m%d").date() + dt.timedelta(days=days)
    return int(d.strftime("%Y%m%d"))


def match_nhl_ids(events: list[dict], nhl_games: Iterable[dict]) -> None:
    """Sets `nhl_game_id` / `match_note` on each event in place.

    Matches on (date, home, away); falls back to the same pairing one day later or
    earlier (UTC-dated or rescheduled games). Each NHL id is used at most once."""
    index: dict[tuple[int, str, str], str] = {}
    for g in nhl_games:
        index[(int(g["date"]), g["home_team_tri_code"], g["away_team_tri_code"])] = str(g["id"])
    used: set[str] = set()
    candidates = []
    for e in events:
        e["nhl_game_id"], e["match_note"] = None, None
        if not e.get("home_team") or not e.get("away_team"):
            e["match_note"] = "unknown_team"  # All-Star / 4 Nations / exhibition teams
        elif e.get("status") in DEAD_STATUSES:
            # ESPN keeps the postponed listing as its own event; the replayed game
            # gets a new event id on the new date, which is the one we match.
            e["match_note"] = "postponed"
        else:
            candidates.append(e)
    # exact dates first so a shifted match can never steal another event's game
    for shift, note in ((0, "exact"), (-1, "date-1"), (1, "date+1")):
        for e in candidates:
            if e["nhl_game_id"]:
                continue
            gid = index.get((_shift_date(e["date"], shift), e["home_team"], e["away_team"]))
            if gid and gid not in used:
                e["nhl_game_id"], e["match_note"] = gid, note
                used.add(gid)
    for e in candidates:
        if not e["nhl_game_id"]:
            e["match_note"] = "unmatched"


def season_label(yyyymmdd: int) -> str:
    """NHL season label like 20232024 from a local game date (seasons roll over in
    August, except the 2020 bubble playoffs in Aug-Sep 2020 belong to 2019-20)."""
    y, m = yyyymmdd // 10000, (yyyymmdd // 100) % 100
    if y == 2020 and m in (8, 9):
        return "20192020"
    start = y if m >= 9 else y - 1  # 2020-21 ran Jan-Jul 2021 -> start 2020 (m<9)
    return f"{start}{start + 1}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

GAME_COLUMNS = [
    "date", "season", "season_type", "espn_event_id", "nhl_game_id", "match_note",
    "start_utc", "status", "completed", "home_team", "away_team", "home_espn_abbr",
    "away_espn_abbr", "home_score", "away_score",
    "n_books", "n_books_total", "books", "consensus_home_ml", "consensus_away_ml",
    "home_prob_novig", "away_prob_novig", "overround", "total_line",
    "open_home_prob_novig", "open_total_line",
]
BOOK_COLUMNS = [
    "date", "season", "espn_event_id", "nhl_game_id", "home_team", "away_team",
    "provider_id", "provider", "is_live", "valid_2way", "home_ml", "away_ml", "overround",
    "home_prob", "away_prob", "total", "over_odds", "under_odds", "home_spread",
    "open_home_ml", "open_away_ml", "open_home_prob", "close_home_ml", "close_away_ml",
    "open_total", "close_total",
]


def build(start: dt.date, end: dt.date, cache_dir: str, workers: int,
          games_csv: str | None, include_preseason: bool):
    import pandas as pd

    client = EspnClient(cache_dir, workers=workers)
    events = fetch_events(client, start, end)
    if not include_preseason:
        events = [e for e in events if e["season_type"] != "preseason"]
    logger.info("%d events to fetch odds for", len(events))
    books = fetch_book_rows(client, events)

    nhl_games = pd.read_csv(games_csv).to_dict("records") if games_csv else []
    match_nhl_ids(events, nhl_games)

    game_rows, book_rows = [], []
    for e in events:
        e["season"] = season_label(e["date"])
        rows = books.get(e["espn_event_id"])
        if rows is None:
            e["fetch_failed"] = True
            rows = []
        game_rows.append({**e, **consensus(rows)})
        for r in rows:
            book_rows.append({**{k: e.get(k) for k in ("date", "season", "espn_event_id", "nhl_game_id",
                                                        "home_team", "away_team")}, **r})
    games_df = pd.DataFrame(game_rows)
    games_df = games_df[[c for c in GAME_COLUMNS if c in games_df.columns]]
    books_df = pd.DataFrame(book_rows, columns=BOOK_COLUMNS)
    for df in (games_df, books_df):
        if "nhl_game_id" in df:
            df["nhl_game_id"] = df["nhl_game_id"].astype("Int64")
    return games_df, books_df, client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (inclusive)")
    parser.add_argument("--out", required=True, help="per-game consensus CSV; per-book rows go to <out>_books.csv")
    parser.add_argument("--cache-dir", help="raw JSON cache (default: <out dir>/espn_cache)")
    parser.add_argument("--games-csv", help="NHL games CSV (id,date,home_team_tri_code,away_team_tri_code,...) for id matching")
    parser.add_argument("--workers", type=int, default=4, help="max concurrent requests (keep small)")
    parser.add_argument("--include-preseason", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    start = dt.date.fromisoformat(args.start)
    end = min(dt.date.fromisoformat(args.end), dt.date.today())
    out = Path(args.out)
    cache_dir = args.cache_dir or str(out.parent / "espn_cache")

    games_df, books_df, client = build(start, end, cache_dir, args.workers, args.games_csv, args.include_preseason)
    out.parent.mkdir(parents=True, exist_ok=True)
    games_df.to_csv(out, index=False)
    books_path = out.with_name(out.stem + "_books.csv")
    books_df.to_csv(books_path, index=False)

    summary = games_df.assign(has_ml=games_df["home_prob_novig"].notna()).groupby("season").agg(
        games=("espn_event_id", "size"), with_ml=("has_ml", "sum"),
        matched=("nhl_game_id", lambda s: s.notna().sum()))
    print(summary.to_string())
    print(f"wrote {len(games_df)} games -> {out}, {len(books_df)} book rows -> {books_path}; "
          f"{client.fetched} network fetches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
