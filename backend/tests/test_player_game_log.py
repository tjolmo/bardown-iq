"""The player page's game logs: a season's (or the last n) games, oldest first, each with the model's pre-game
expectations from the forward test's log."""
import asyncio
import datetime
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Games, GoalieGameLog, PlayerPredictionLog, SkaterGameLog
from app.routers import player_router as R

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
PID = 8480001


def _zeros(model) -> dict:
    """Every column of a game log at a neutral value, so a test only names what it checks."""
    out = {}
    for c in model.__table__.columns:
        py = c.type.python_type
        out[c.name] = NOW if py is datetime.datetime else "" if py is str else py(0)
    return out


def skater_log(gid, date, season=2026, **kw):
    row = {**_zeros(SkaterGameLog), "game_id": gid, "player_id": PID, "name": "P", "season": season,
           "home_away": "HOME", "player_team_tricode": "TOR", "opposing_team_tricode": "MTL", "game_date": date, **kw}
    return SkaterGameLog(**row)


def goalie_log(gid, date, season=2026, **kw):
    row = {**_zeros(GoalieGameLog), "game_id": gid, "player_id": PID, "name": "P", "season": season,
           "home_away": "AWAY", "player_team_tricode": "MTL", "opposing_team_tricode": "NYR", "game_date": date, **kw}
    return GoalieGameLog(**row)


def game(gid, date, start):
    return Games(id=gid, home_team_tri_code="TOR", away_team_tri_code="MTL", season=20262027, date=date, venue="v",
                 start_time=start, game_state="OFF", last_updated=NOW)


def logged(gid, date, stat, expected, at, role="skater"):
    return PlayerPredictionLog(run_id=f"r{at.isoformat()}", model_version="m", logged_at=at, game_id=gid,
                               game_date=date, player_id=PID, team_tri_code="TOR", role=role, stat=stat,
                               expected=expected)


def run(rows, call):
    async def go():
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            db.add_all(rows)
            await db.commit()
            return await call(db)
    return asyncio.run(go())


def test_season_log_is_oldest_first_with_the_last_pregame_expectations():
    start = datetime.datetime(2026, 10, 10, 23, 0, tzinfo=UTC)
    rows = [
        skater_log(2, 20261010, goals=1, primary_assists=1, secondary_assists=1, points=3, shots_on_goal=4),
        skater_log(1, 20261008, goals=0, points=0),
        skater_log(0, 20260410, season=2025, goals=5),   # last season: not in this one's log
        game(2, 20261010, start),
        logged(2, 20261010, "points", 0.9, start - datetime.timedelta(hours=6)),
        logged(2, 20261010, "points", 1.1, start - datetime.timedelta(hours=1)),   # the last run before puck drop
        logged(2, 20261010, "points", 3.0, start + datetime.timedelta(hours=1)),   # after puck drop: never used
        logged(2, 20261010, "shots_on_goal", 3.2, start - datetime.timedelta(hours=1)),
    ]
    out = run(rows, lambda db: R.get_skater_season_game_log(PID, "2026", db))
    assert [g.game_id for g in out] == [1, 2]
    assert out[1].date == "2026-10-10"
    assert out[1].assists == 2 and out[1].points == 3 and out[1].shots_on_goal == 4
    assert out[1].expected == {"points": 1.1, "shots_on_goal": 3.2}
    assert out[0].expected == {}


def test_last_n_crosses_seasons():
    rows = [skater_log(i, d, season=s) for i, (d, s) in enumerate(
        [(20260401, 2025), (20260410, 2025), (20261008, 2026), (20261010, 2026)])]
    out = run(rows, lambda db: R.get_skater_recent_game_log(PID, 3, db))
    assert [g.date for g in out] == ["2026-04-10", "2026-10-08", "2026-10-10"]


def test_goalie_saves_leave_the_goals_out_of_the_shots():
    start = datetime.datetime(2026, 10, 10, 23, 0, tzinfo=UTC)
    rows = [goalie_log(5, 20261010, sog=31, goals_against=2, toi=3600.0), game(5, 20261010, start),
            logged(5, 20261010, "saves", 27.4, start - datetime.timedelta(hours=2), role="goalie")]
    [g] = run(rows, lambda db: R.get_goalie_season_game_log(PID, "2026", db))
    assert (g.shots_against, g.saves, g.goals_against) == (31, 29, 2)
    assert g.expected == {"saves": 27.4}
