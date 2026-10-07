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

# usage: python -m app.backfill --seasons 2020 2021 2022 --games-seasons 2008 2009
#        python -m app.backfill --odds 2019-04-01 2026-10-06 [--odds-cache DIR]
#        python -m app.backfill --birth-dates
#        python -m app.backfill --props 2023-10-01 2026-10-07 [--odds-cache DIR]
# upserts, so re-running a season is safe
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill MoneyPuck skater/goalie game logs and NHL schedules/scores")
    parser.add_argument("--seasons", type=int, nargs="+", default=[], help="game log season start years, e.g. 2024")
    parser.add_argument("--games-seasons", type=int, nargs="+", default=[], help="season start years to upsert games/final scores for (no player fetch)")
    parser.add_argument("--team-stats-seasons", type=int, nargs="+", default=[], help="season start years of MoneyPuck team game stats")
    parser.add_argument("--odds", nargs=2, metavar=("START", "END"), type=datetime.date.fromisoformat, help="ESPN closing odds date range (YYYY-MM-DD, inclusive)")
    parser.add_argument("--props", nargs=2, metavar=("START", "END"), type=datetime.date.fromisoformat, help="ESPN player prop odds date range (YYYY-MM-DD, inclusive)")
    parser.add_argument("--birth-dates", action="store_true", help="fill players.birth_date from the NHL landing endpoint (players missing one)")
    parser.add_argument("--odds-cache", help="directory to cache raw ESPN JSON in (default: a temp dir)")
    args = parser.parse_args()
    if args.birth_dates:
        logging.basicConfig(level=logging.INFO)
        asyncio.run(backfill_birth_dates())
        raise SystemExit(0)
    if not args.seasons and not args.games_seasons and not args.team_stats_seasons and not args.odds and not args.props:
        parser.error("pass --seasons, --games-seasons, --team-stats-seasons, --odds and/or --props")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(backfill(args.seasons, args.games_seasons, args.team_stats_seasons,
                         tuple(args.odds) if args.odds else None, args.odds_cache,
                         tuple(args.props) if args.props else None))
