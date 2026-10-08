"""Roster refresh skips teams without recent games (relocated franchises the NHL has no roster for)."""
import asyncio
import datetime
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.crud.teams import get_all_tri_codes_update_roster
from app.models import Base, Games, Team

NOW = datetime.datetime.now(datetime.timezone.utc)


def test_only_active_stale_teams_need_rosters():
    async def go():
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            db.add_all([Team(tri_code=t, current_name=t, franchise_id=i, last_updated=NOW, roster_last_updated=r)
                        for i, (t, r) in enumerate([("TOR", None), ("MTL", None), ("UTA", NOW), ("ARI", None)])])
            today = int(datetime.date.today().strftime("%Y%m%d"))
            db.add(Games(id=1, home_team_tri_code="TOR", away_team_tri_code="MTL", season=20262027, date=today,
                         venue="v", start_time=NOW, game_state="FUT", last_updated=NOW))
            db.add(Games(id=2, home_team_tri_code="UTA", away_team_tri_code="TOR", season=20262027, date=today,
                         venue="v", start_time=NOW, game_state="FUT", last_updated=NOW))
            db.add(Games(id=3, home_team_tri_code="ARI", away_team_tri_code="TOR", season=20232024, date=20240401,
                         venue="v", start_time=NOW, game_state="OFF", last_updated=NOW))
            await db.commit()
            return sorted(await get_all_tri_codes_update_roster(db))
    # UTA was updated today, ARI hasn't played in over a year
    assert asyncio.run(go()) == ["MTL", "TOR"]
