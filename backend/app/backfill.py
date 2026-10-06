import argparse
import asyncio
import datetime
import logging

from app.schedules import HISTORICAL_TEAMS, add_old_teams_to_db, backfill_season_games, scrape_all_player_logs, scrape_team_stats, fetch_game_odds_for_range

async def backfill(seasons: list[int], games_seasons: list[int], team_stats_seasons: list[int],
                   odds_range: tuple[datetime.date, datetime.date] | None = None, odds_cache: str | None = None):
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

# usage: python -m app.backfill --seasons 2020 2021 2022 --games-seasons 2008 2009
#        python -m app.backfill --odds 2019-04-01 2026-10-06 [--odds-cache DIR]
# upserts, so re-running a season is safe
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill MoneyPuck skater/goalie game logs and NHL schedules/scores")
    parser.add_argument("--seasons", type=int, nargs="+", default=[], help="game log season start years, e.g. 2024")
    parser.add_argument("--games-seasons", type=int, nargs="+", default=[], help="season start years to upsert games/final scores for (no player fetch)")
    parser.add_argument("--team-stats-seasons", type=int, nargs="+", default=[], help="season start years of MoneyPuck team game stats")
    parser.add_argument("--odds", nargs=2, metavar=("START", "END"), type=datetime.date.fromisoformat, help="ESPN closing odds date range (YYYY-MM-DD, inclusive)")
    parser.add_argument("--odds-cache", help="directory to cache raw ESPN JSON in (default: a temp dir)")
    args = parser.parse_args()
    if not args.seasons and not args.games_seasons and not args.team_stats_seasons and not args.odds:
        parser.error("pass --seasons, --games-seasons, --team-stats-seasons and/or --odds")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(backfill(args.seasons, args.games_seasons, args.team_stats_seasons,
                         tuple(args.odds) if args.odds else None, args.odds_cache))
