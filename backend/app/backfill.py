import argparse
import asyncio
import logging

from app.schedules import scrape_all_player_logs

# usage: python -m app.backfill --seasons 2020 2021 2022
# upserts, so re-running a season is safe
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill MoneyPuck skater/goalie game logs")
    parser.add_argument("--seasons", type=int, nargs="+", required=True, help="season start years, e.g. 2024")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(scrape_all_player_logs(args.seasons))
