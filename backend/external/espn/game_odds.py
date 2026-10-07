"""Per-game ESPN closing odds matched to NHL game ids, shaped for the game_odds table."""

from __future__ import annotations

import datetime as dt
import logging
import tempfile

from external.espn.odds import EspnClient, consensus, fetch_book_rows, fetch_events, match_nhl_ids

logger = logging.getLogger(__name__)


def build_game_odds_rows(events: list[dict], books: dict[str, list[dict] | None], nhl_games: list[dict]) -> list[dict]:
    """game_odds rows for events that match an NHL game and have a consensus price.
    `nhl_games` are dicts with id/date/home_team_tri_code/away_team_tri_code."""
    match_nhl_ids(events, nhl_games)
    teams = {int(g["id"]): (int(g["date"]), g["home_team_tri_code"], g["away_team_tri_code"]) for g in nhl_games}
    rows = []
    for e in events:
        if not e["nhl_game_id"]:
            continue
        c = consensus(books.get(e["espn_event_id"]) or [])
        if c["home_prob_novig"] is None:
            continue
        game_id = int(e["nhl_game_id"])
        date, home, away = teams[game_id]  # NHL's date, not ESPN's (they differ for shifted matches)
        rows.append({
            "game_id": game_id,
            "date": date,
            "home_team_tri_code": home,
            "away_team_tri_code": away,
            "home_moneyline": c["consensus_home_ml"],
            "away_moneyline": c["consensus_away_ml"],
            "home_prob_novig": c["home_prob_novig"],
            "open_home_prob_novig": c["open_home_prob_novig"],
            "open_home_moneyline": c["open_home_ml"],
            "open_away_moneyline": c["open_away_ml"],
            "total_line": c["total_line"],
            "open_total_line": c["open_total_line"],
            "n_books": c["n_books"],
            "books": c["books"] or None,
            "espn_event_id": int(e["espn_event_id"]),
            # snapshot-only fields (game_odds has no columns for them)
            "total_over_price": c.get("total_over_price"),
            "total_under_price": c.get("total_under_price"),
        })
    return rows


def fetch_game_odds(start: dt.date, end: dt.date, nhl_games: list[dict],
                    cache_dir: str | None = None, workers: int = 4) -> tuple[list[dict], EspnClient]:
    """Blocking: fetches ESPN odds for start..end (inclusive) and matches them to `nhl_games`.
    Without a cache_dir the raw JSON goes to a throwaway temp dir."""
    if cache_dir is None:
        with tempfile.TemporaryDirectory(prefix="espn_odds_") as tmp:
            return fetch_game_odds(start, end, nhl_games, tmp, workers)
    client = EspnClient(cache_dir, workers=workers)
    events = [e for e in fetch_events(client, start, end) if e["season_type"] != "preseason"]
    books = fetch_book_rows(client, events)
    rows = build_game_odds_rows(events, books, nhl_games)
    logger.info("odds %s..%s: %d events, %d matched with prices, %d network fetches",
                start, end, len(events), len(rows), client.fetched)
    return rows, client
