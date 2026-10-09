import asyncio
import datetime
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, PredictionLog
from app.crud.prediction_log import get_pregame_home_win_probs

START = datetime.datetime(2026, 10, 9, 23, 0, tzinfo=datetime.timezone.utc)


def log(game_id, hours_before_start, p, run):
    return PredictionLog(run_id=run, model_version="v1", logged_at=START - datetime.timedelta(hours=hours_before_start),
                         game_id=game_id, game_date=20261009, start_time=START, home_team_tri_code="VGK",
                         away_team_tri_code="EDM", home_win_prob=p)


def lookup(rows, game_ids):
    async def go():
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine)() as db:
            db.add_all(rows)
            await db.commit()
            result = await get_pregame_home_win_probs(db, game_ids)
        await engine.dispose()
        return result
    return asyncio.run(go())


def test_latest_pregame_log_wins_and_post_start_logs_are_ignored():
    rows = [log(1, 2, 0.40, "a"), log(1, 1, 0.45, "b"), log(1, -1, 0.90, "late"), log(2, 2, 0.60, "a")]
    assert lookup(rows, [1, 2, 3]) == {1: 0.45, 2: 0.60}


def test_no_games_no_query():
    assert lookup([], []) == {}
