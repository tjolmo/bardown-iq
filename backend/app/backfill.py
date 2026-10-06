import argparse
import asyncio
import logging

from app.schedules import HISTORICAL_TEAMS, add_old_teams_to_db, backfill_season_games, scrape_all_player_logs

async def backfill(seasons: list[int], games_seasons: list[int]):
    # relocated teams (ATL, PHX) must exist before their games/logs satisfy the tri code FKs
    await add_old_teams_to_db(HISTORICAL_TEAMS)
    if games_seasons:
        await backfill_season_games(games_seasons)
    if seasons:
        await scrape_all_player_logs(seasons)

# usage: python -m app.backfill --seasons 2020 2021 2022 --games-seasons 2008 2009
# upserts, so re-running a season is safe
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill MoneyPuck skater/goalie game logs and NHL schedules/scores")
    parser.add_argument("--seasons", type=int, nargs="+", default=[], help="game log season start years, e.g. 2024")
    parser.add_argument("--games-seasons", type=int, nargs="+", default=[], help="season start years to upsert games/final scores for (no player fetch)")
    args = parser.parse_args()
    if not args.seasons and not args.games_seasons:
        parser.error("pass --seasons and/or --games-seasons")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(backfill(args.seasons, args.games_seasons))
