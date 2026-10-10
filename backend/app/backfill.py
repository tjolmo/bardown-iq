import argparse
import asyncio
import datetime
import logging

from app.database import AsyncSessionLocal
from app.crud.players import get_player_ids_missing_birth_date, set_player_birth_dates
from external.http import gather_bounded, close_client
from external.nhl.players import fetch_and_get_players_info

from app.schedules import HISTORICAL_TEAMS, add_old_teams_to_db, backfill_season_games, scrape_all_player_logs, scrape_team_stats, fetch_game_odds_for_range, fetch_player_prop_odds_for_range

async def backfill(seasons: list[int], games_seasons: list[int], team_stats_seasons: list[int],
                   odds_range: tuple[datetime.date, datetime.date] | None = None, odds_cache: str | None = None,
                   props_range: tuple[datetime.date, datetime.date] | None = None):
    # relocated teams (ATL, PHX) must exist before their games/logs satisfy the tri code FKs
    await add_old_teams_to_db(HISTORICAL_TEAMS)
    if games_seasons:
        await backfill_season_games(games_seasons)
    if seasons:
        await scrape_all_player_logs(seasons)
    if team_stats_seasons:
        await scrape_team_stats(team_stats_seasons)
    if odds_range:
        # matches against the games table, so run after --games-seasons
        await fetch_game_odds_for_range(*odds_range, cache_dir=odds_cache)
    if props_range:
        # matches against games, players and game logs, so run after those backfills
        await fetch_player_prop_odds_for_range(*props_range, cache_dir=odds_cache)

async def backfill_birth_dates(concurrency: int = 4, chunk: int = 200):
    """Fills players.birth_date from the NHL player landing endpoint for every player missing one."""
    async with AsyncSessionLocal() as db:
        player_ids = await get_player_ids_missing_birth_date(db)
    logging.info("birth dates: %d players to fetch", len(player_ids))
    failed, no_date, filled = [], [], 0
    for start in range(0, len(player_ids), chunk):
        ids = player_ids[start:start + chunk]
        infos = await gather_bounded([fetch_and_get_players_info(pid) for pid in ids], limit=concurrency)
        found = {}
        for pid, info in zip(ids, infos):
            if info is None:
                failed.append(pid)
            elif info.birth_date is None:
                no_date.append(pid)
            else:
                found[pid] = info.birth_date
        async with AsyncSessionLocal() as db:
            await set_player_birth_dates(db, found)
        filled += len(found)
        logging.info("birth dates: %d/%d done, %d filled", start + len(ids), len(player_ids), filled)
    await close_client()
    logging.info("birth dates: filled %d, fetch failed %d %s, no birthDate %d %s",
                 filled, len(failed), failed[:50], len(no_date), no_date[:50])

async def backfill_actual_starters(min_season: int = 2008, max_season: int | None = None, chunk: int = 200,
                                  concurrency: int = 4, log_path: str | None = None):
    """Actual starting goalies (game_starters, source "nhl") for every finished game from `min_season` on that lacks
    them. Commits per chunk, so an interrupted run resumes where it stopped; games whose fetch failed are retried
    by the next run. `log_path` appends each chunk's counts (incl. boxscore/play-by-play disagreements) as JSON lines."""
    import json
    from app.crud.game_starters import get_games_missing_actual_starters
    from app.schedules import record_actual_starters
    async with AsyncSessionLocal() as db:
        game_ids = await get_games_missing_actual_starters(db, min_season, max_season)
    logging.info("actual starters: %d games to fetch", len(game_ids))
    totals = {"games": 0, "failed": [], "boxscore": 0, "pbp": 0, "teams_missing": [], "disagree": []}
    for start in range(0, len(game_ids), chunk):
        stats = await record_actual_starters(game_ids[start:start + chunk], concurrency)
        for k, v in stats.items():
            totals[k] += v
        if log_path:
            with open(log_path, "a") as f:
                f.write(json.dumps(stats) + "\n")
        logging.info("actual starters: %d/%d games, %d team-games via boxscore flag, %d via play-by-play, %d failed, "
                     "%d incomplete, %d disagree", start + stats["games"],
                     len(game_ids), totals["boxscore"], totals["pbp"], len(totals["failed"]), len(totals["teams_missing"]),
                     len(totals["disagree"]))
    await close_client()
    logging.info("actual starters done: failed %s, incomplete %s, boxscore/pbp disagree %s",
                 totals["failed"][:50], totals["teams_missing"][:50], totals["disagree"][:50])

async def backfill_game_lineups(min_season: int, max_season: int | None = None, chunk: int = 100, concurrency: int = 4):
    """Lineups, scratches and shift-chart deployment (game_lineups, game_units) of every finished game of the
    seasons that lacks ice time, including games whose shift chart was missing before. Commits per game, so an
    interrupted run resumes where it stopped."""
    from app.crud.lineups import get_games_missing_deployment
    from app.schedules import record_game_lineups
    async with AsyncSessionLocal() as db:
        games = await get_games_missing_deployment(db, min_season, max_season, recheck_days=None)
    logging.info("game lineups: %d games to fetch", len(games))
    totals = {"posted": 0, "with_shifts": 0, "no_shifts": [], "not_posted": [], "failed": []}
    for start in range(0, len(games), chunk):
        stats = await record_game_lineups(games[start:start + chunk], concurrency=concurrency)
        for k in totals:
            totals[k] += stats[k]
        logging.info("game lineups: %d/%d games, %d with ice time, %d without a shift chart, %d failed",
                     start + stats["games"], len(games), totals["with_shifts"], len(totals["no_shifts"]),
                     len(totals["failed"]))
    await close_client()
    logging.info("game lineups done: no shift chart %s, not posted %s, failed %s", totals["no_shifts"][:50],
                 totals["not_posted"][:50], totals["failed"][:50])

# usage: python -m app.backfill --seasons 2020 2021 2022 --games-seasons 2008 2009
#        python -m app.backfill --odds 2019-04-01 2026-10-06 [--odds-cache DIR]
#        python -m app.backfill --birth-dates
#        python -m app.backfill --actual-starters [--starter-seasons 2008 2025] [--starters-log FILE]
#        python -m app.backfill --props 2023-10-01 2026-10-07 [--odds-cache DIR]
#        python -m app.backfill --lineups [--lineup-seasons 2026 2026]
# upserts, so re-running a season is safe
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill MoneyPuck skater/goalie game logs and NHL schedules/scores")
    parser.add_argument("--seasons", type=int, nargs="+", default=[], help="game log season start years, e.g. 2024")
    parser.add_argument("--games-seasons", type=int, nargs="+", default=[], help="season start years to upsert games/final scores for (no player fetch)")
    parser.add_argument("--team-stats-seasons", type=int, nargs="+", default=[], help="season start years of MoneyPuck team game stats")
    parser.add_argument("--odds", nargs=2, metavar=("START", "END"), type=datetime.date.fromisoformat, help="ESPN closing odds date range (YYYY-MM-DD, inclusive)")
    parser.add_argument("--props", nargs=2, metavar=("START", "END"), type=datetime.date.fromisoformat, help="ESPN player prop odds date range (YYYY-MM-DD, inclusive)")
    parser.add_argument("--birth-dates", action="store_true", help="fill players.birth_date from the NHL landing endpoint (players missing one)")
    parser.add_argument("--actual-starters", action="store_true", help="store who actually started every finished game (NHL play-by-play / boxscore) in game_starters")
    parser.add_argument("--starter-seasons", type=int, nargs=2, metavar=("FIRST", "LAST"), default=[2008, None], help="season start years for --actual-starters (default 2008 onward)")
    parser.add_argument("--starters-log", help="append per-chunk --actual-starters counts as JSON lines to this file")
    parser.add_argument("--lineups", action="store_true", help="store every finished game's lineups, scratches and shift-chart deployment (game_lineups, game_units)")
    parser.add_argument("--lineup-seasons", type=int, nargs=2, metavar=("FIRST", "LAST"), default=None, help="season start years for --lineups (default: the current season)")
    parser.add_argument("--odds-cache", help="directory to cache raw ESPN JSON in (default: a temp dir)")
    args = parser.parse_args()
    if args.birth_dates:
        logging.basicConfig(level=logging.INFO)
        asyncio.run(backfill_birth_dates())
        raise SystemExit(0)
    if args.actual_starters:
        logging.basicConfig(level=logging.INFO)
        asyncio.run(backfill_actual_starters(*args.starter_seasons, log_path=args.starters_log))
        raise SystemExit(0)
    if args.lineups:
        from app.schedules import get_current_season_start_year
        logging.basicConfig(level=logging.INFO)
        first, last = args.lineup_seasons or (get_current_season_start_year(),) * 2
        asyncio.run(backfill_game_lineups(first, last))
        raise SystemExit(0)
    if not args.seasons and not args.games_seasons and not args.team_stats_seasons and not args.odds and not args.props:
        parser.error("pass --seasons, --games-seasons, --team-stats-seasons, --odds and/or --props")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(backfill(args.seasons, args.games_seasons, args.team_stats_seasons,
                         tuple(args.odds) if args.odds else None, args.odds_cache,
                         tuple(args.props) if args.props else None))
