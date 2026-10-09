import asyncio
import datetime
import os
import sys

import numpy as np
import pandas as pd

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Player, SkaterGameLog, SkaterGameShare
from predictions import features as F, predict as P, shares as S
from predictions.data import load_game_mates

NOW = datetime.datetime(2026, 10, 8, 3, 0, tzinfo=datetime.timezone.utc)
POSITIONS = ["C", "L", "D", "D"]


def run(coro_fn):
    async def go():
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return await coro_fn(db)
    return asyncio.run(go())


def log(gid, pid, team, season=2025, date=20251010, toi=1000.0, pp_toi=120.0, sog=2, xg=0.5):
    return SkaterGameLog(game_id=gid, player_id=pid, name=str(pid), season=season, player_team_tricode=team,
                         opposing_team_tricode="BBB" if team == "AAA" else "AAA", game_date=date, goals=0,
                         primary_assists=0, secondary_assists=0, points=0, x_goals=xg, toi=toi, high_danger_shots=0,
                         shot_attempts=0, on_ice_x_goals_percentage=0.5, game_score=0.0, shots_on_goal=sog,
                         pp_toi=pp_toi, last_updated=NOW)


async def _seed(db):
    """Two teams of four skaters over three games (two last season, one this season); BBB never has PP time."""
    db.add_all([Player(id=pid, first_name="F", last_name=str(pid), position=POSITIONS[(pid - 1) % 10], last_updated=NOW)
                for pid in (1, 2, 3, 4, 11, 12, 13, 14)])
    for gid, season, date in ((100, 2024, 20250310), (101, 2024, 20250312), (200, 2025, 20251010)):
        for team, base in (("AAA", 1), ("BBB", 11)):
            for k in range(4):
                db.add(log(gid, base + k, team, season, date, toi=1000.0 - 100 * k + gid,
                           pp_toi=(120.0 if k < 2 else 0.0) if team == "AAA" else 0.0, sog=2 + k, xg=0.5 + k))
    await db.commit()


async def _stored(db) -> pd.DataFrame:
    rows = (await db.execute(select(SkaterGameShare))).scalars().all()
    df = pd.DataFrame([{c: getattr(r, c) for c in ["game_id", "player_id"] + F.SKATER_SHARE_STATS} for r in rows])
    return df.astype({c: float for c in F.SKATER_SHARE_STATS}).sort_values(["game_id", "player_id"]).reset_index(drop=True)


def _expected(mates: pd.DataFrame) -> pd.DataFrame:
    return F.skater_shares(mates).sort_values(["game_id", "player_id"]).reset_index(drop=True)


def test_refresh_stores_exactly_the_computed_shares():
    async def go(db):
        await _seed(db)
        out = await S.refresh_skater_shares(db, now=NOW)
        return out, await _stored(db), _expected(await load_game_mates(db, [100, 101, 200]))
    out, stored, expected = run(go)
    assert out == {"games": 3, "rows": 24}
    pd.testing.assert_frame_equal(stored, expected[stored.columns], check_dtype=False)
    # a team without PP time has no PP share (NULL, read back as NaN), not 0
    assert stored.loc[stored["player_id"] == 11, "pp_share"].isna().all()


def test_refresh_redoes_the_latest_season_and_games_with_new_rows():
    async def go(db):
        await _seed(db)
        await S.refresh_skater_shares(db, now=NOW)
        # a re-scrape changes this season's game, and a late row appears in last season's game 100
        (await db.get(SkaterGameLog, (200, 1))).shots_on_goal = 20
        db.add(Player(id=5, first_name="F", last_name="5", position="C", last_updated=NOW))
        db.add(log(100, 5, "AAA", 2024, 20250310, sog=6))
        await db.commit()
        stale = await S.stale_share_games(db)
        out = await S.refresh_skater_shares(db, now=NOW)
        return stale, out, await _stored(db), _expected(await load_game_mates(db, [100, 101, 200]))
    stale, out, stored, expected = run(go)
    assert stale == [100, 200]      # game 101 is untouched
    assert out == {"games": 2, "rows": 17}
    pd.testing.assert_frame_equal(stored, expected[stored.columns], check_dtype=False)


def test_live_shares_match_the_full_computation_with_partial_or_no_table():
    async def go(db):
        await _seed(db)
        full = F.skater_shares(await load_game_mates(db, [100, 101, 200]))
        empty = await P._skater_shares(db, 1, [100, 101, 200])          # table exists but not refreshed yet
        await S.refresh_skater_shares(db, now=NOW)
        await db.execute(text("DELETE FROM skater_game_shares WHERE game_id = 200"))   # scraped after the refresh
        await db.commit()
        partial = await P._skater_shares(db, 1, [100, 101, 200])
        await db.execute(text("DROP TABLE skater_game_shares"))          # not migrated
        await db.commit()
        missing = await P._skater_shares(db, 1, [100, 101, 200])
        return full, empty, partial, missing
    full, empty, partial, missing = run(go)
    own = lambda df: (df[df["player_id"] == 1].sort_values("game_id").reset_index(drop=True)
                      [["game_id", "player_id"] + F.SKATER_SHARE_STATS])
    for got in (empty, partial, missing):
        pd.testing.assert_frame_equal(own(got), own(full), check_dtype=False)


def test_teammate_quality_only_needs_the_players_games():
    """predict_skater passes only the lineups of the player's own games; the result must not change."""
    lineups = pd.DataFrame({"game_id": np.repeat([300, 301, 302], 19), "team": "AAA",
                            "player_id": np.tile(np.arange(1, 20), 3), "exp_toi": np.tile(np.linspace(0.4, 0.1, 19), 3),
                            "exp_game_score": np.arange(57.0), "exp_points": 0.5})
    lineups = lineups.groupby(["game_id", "team"]).head(F.LINEUP_SIZE)
    # a player in some lineups, and one whose games have no lineup at all (NaN either way)
    for games in ([300, 302, 303], [303]):
        players = pd.DataFrame({"game_id": games, "team": "AAA", "player_id": 5})
        part = F.teammate_quality(players, lineups[lineups["game_id"].isin(players["game_id"])])
        pd.testing.assert_frame_equal(part, F.teammate_quality(players, lineups), check_dtype=False)
