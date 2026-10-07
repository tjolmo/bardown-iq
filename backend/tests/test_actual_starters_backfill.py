"""Which finished games still need their actual starters (the resumable --actual-starters backfill / nightly step)."""
import asyncio
import datetime
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, Games, GameStarter
from app.crud.game_starters import actual_starter_rows, get_games_missing_actual_starters

NOW = datetime.datetime(2025, 10, 8, 23, 0, tzinfo=datetime.timezone.utc)


def missing(games, starters, **kwargs):
    """games: (id, season, game_state); starters: (game_id, team, source, status)."""
    async def go():
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine)() as db:
            for gid, season, state in games:
                db.add(Games(id=gid, home_team_tri_code="TOR", away_team_tri_code="MTL", season=season, date=20251008,
                             venue="v", start_time=NOW, game_state=state, last_updated=NOW))
            for gid, team, source, status in starters:
                db.add(GameStarter(game_id=gid, team=team, player_id=1, status=status, source=source, fetched_at=NOW))
            await db.commit()
            return await get_games_missing_actual_starters(db, **kwargs)
    return asyncio.run(go())


def test_finished_games_without_both_actual_starters():
    games = [(2008020001, 20082009, "OFF"), (2008020002, 20082009, "FINAL"), (2008020003, 20082009, "OFF"),
             (2008030111, 20082009, "OFF"), (2008010001, 20082009, "OFF"),    # playoffs kept, preseason not
             (2025020001, 20252026, "FUT"), (2025020002, 20252026, "OFF")]
    starters = [(2008020001, "TOR", "nhl", "actual"), (2008020001, "MTL", "nhl", "actual"),
                (2008020002, "TOR", "nhl", "actual"),                                  # one team only: refetch
                (2008020003, "TOR", "espn", "confirmed"), (2008020003, "MTL", "espn", "confirmed")]  # pre-game picks only
    assert missing(games, starters) == [2008020002, 2008020003, 2008030111, 2025020002]
    assert missing(games, starters, min_season=2025) == [2025020002]
    assert missing(games, starters, max_season=2008, limit=2) == [2008020002, 2008020003]


def test_actual_starter_rows():
    assert actual_starter_rows(7, {"TOR": 1}) == [{"game_id": 7, "team": "TOR", "player_id": 1, "status": "actual", "source": "nhl"}]
