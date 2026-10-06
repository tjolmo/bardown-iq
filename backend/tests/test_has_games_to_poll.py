import asyncio
import datetime
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, Games
from app.crud.games import has_games_to_poll

NOW = datetime.datetime(2025, 10, 8, 23, 0, tzinfo=datetime.timezone.utc)


def check(*games):
    """games: (start_time offset from NOW, game_state). Returns has_games_to_poll."""
    async def go():
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine)() as db:
            for i, (offset, state) in enumerate(games):
                db.add(Games(id=i, home_team_tri_code="TOR", away_team_tri_code="MTL", season=20252026,
                             date=20251008, venue="v", start_time=NOW + offset, game_state=state,
                             last_updated=NOW))
            await db.commit()
            return await has_games_to_poll(db, NOW)
    return asyncio.run(go())


def minutes(m):
    return datetime.timedelta(minutes=m)


def test_no_games():
    assert check() is False


def test_game_far_in_future_is_not_polled():
    assert check((minutes(60), "FUT")) is False


def test_game_about_to_start_is_polled():
    assert check((minutes(5), "FUT")) is True


def test_live_game_is_polled():
    assert check((-minutes(90), "LIVE")) is True


def test_finished_game_is_not_polled():
    assert check((-minutes(200), "OFF"), (-minutes(200), "FINAL")) is False


def test_stale_postponed_game_is_not_polled():
    assert check((-minutes(60 * 20), "FUT")) is False
