"""The top skaters and top goalies boards: season totals, the rates, the sort and the goalies' games floor."""
import asyncio
import datetime
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import leaderboards as L
from app.models import Base, GoalieGameLog, Player, SkaterGameLog

NOW = datetime.datetime(2026, 10, 10, 18, 0, tzinfo=datetime.timezone.utc)
SEASON = 2026


def player(pid, pos="C", team="EDM", number=None):
    return Player(id=pid, first_name=f"P{pid}", last_name="X", position=pos, current_team_tri_code=team, number=number,
                  last_updated=NOW)


def skater_log(pid, game_id, date, goals=0, a1=0, a2=0, xg=0.0, toi=1200.0, sog=0, ppp=0, season=SEASON):
    return SkaterGameLog(game_id=game_id, player_id=pid, name=f"P{pid}", season=season, player_team_tricode="EDM",
                         opposing_team_tricode="CGY", game_date=date, goals=goals, primary_assists=a1,
                         secondary_assists=a2, points=goals + a1 + a2, x_goals=xg, toi=toi, high_danger_shots=0,
                         shot_attempts=0, on_ice_x_goals_percentage=0.5, game_score=0.0, shots_on_goal=sog,
                         pp_points=ppp, last_updated=NOW)


def goalie_log(pid, game_id, date, sog=30, ga=2, xga=2.5, toi=3600.0, hd=5, season=SEASON):
    return GoalieGameLog(game_id=game_id, player_id=pid, name=f"P{pid}", season=season, player_team_tricode="EDM",
                         opposing_team_tricode="CGY", game_date=date, toi=toi, x_goals_against=xga, goals_against=ga,
                         unblocked_shot_attempts=sog, x_rebounds=0.0, rebounds=0, x_freeze=0.0, freeze=0, x_sog=0.0,
                         sog=sog, x_play_stopped=0.0, play_stopped=0, x_play_continued_in_zone=0.0,
                         x_play_continued_outside_zone=0.0, flurry_adjusted_x_goals=xga, low_danger_shots=0,
                         medium_danger_shots=0, high_danger_shots=hd, low_danger_x_goals=0.0,
                         medium_danger_x_goals=0.0, high_danger_x_goals=0.0, blocked_shot_attempts=0,
                         penality_minutes=0, penalties=0, last_updated=NOW)


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


def skaters():
    return [
    player(1), player(2, pos="D"), player(3, pos="L"),
    player(4, team=None),                   # off a roster: not on the board
    player(9, pos="G"),                     # a goalie: not on the skaters board
    # P1: 2 games, 1+2 and 0+1 = 4 points, 1 goal
    skater_log(1, 101, 20261008, goals=1, a1=1, a2=1, xg=0.6, toi=1500, sog=4, ppp=1),
    skater_log(1, 102, 20261009, a1=1, xg=0.4, toi=1200, sog=2),
    # P2 (D): 3 games, 3 goals and 1 assist = 4 points on 0.9 xG
    skater_log(2, 101, 20261008, goals=2, xg=0.3, sog=5),
    skater_log(2, 102, 20261009, goals=1, xg=0.3, sog=3),
    skater_log(2, 103, 20261010, a2=1, xg=0.3, sog=1),
    # P3: 1 game, a hat trick on the power play
    skater_log(3, 101, 20261008, goals=3, xg=1.5, sog=6, ppp=2),
    skater_log(4, 101, 20261008, goals=5),
    skater_log(9, 101, 20261008, goals=5),
    skater_log(1, 50, 20251001, goals=9, season=2025),   # last season
    ]


def test_top_skaters_sums_the_season_and_breaks_ties_on_goals_then_games():
    rows = run(skaters(), lambda db: L.top_skaters(db, SEASON, 10))
    assert [s.player.id for s in rows] == [2, 1, 3]
    p2, p1, p3 = rows
    assert (p2.games, p2.goals, p2.assists, p2.points, p2.shots_on_goal) == (3, 3, 1, 4, 9)
    assert (p1.games, p1.goals, p1.assists, p1.points, p1.pp_points) == (2, 1, 3, 4, 1)
    assert p1.x_goals == pytest.approx(1.0)
    assert p1.toi_per_game == pytest.approx(22.5)
    assert p1.points_per_game == pytest.approx(2.0)
    assert p1.points_by_game == [3, 1]
    assert p2.points_by_game == [2, 1, 1]
    assert p3.points_by_game == [3]


def test_top_skaters_ranks_on_the_sort_asked_for_and_cuts_at_n():
    rows = run(skaters(), lambda db: L.top_skaters(db, SEASON, 2, sort="points_per_game"))
    assert [(s.player.id, s.points_per_game) for s in rows] == [(3, 3.0), (1, 2.0)]
    rows = run(skaters(), lambda db: L.top_skaters(db, SEASON, 10, sort="pp_points"))
    assert [s.player.id for s in rows] == [3, 1, 2]
    rows = run(skaters(), lambda db: L.top_skaters(db, SEASON, 10, sort="x_goals"))
    assert [s.player.id for s in rows] == [3, 1, 2]


def test_top_skaters_filters_forwards_or_defence():
    assert [s.player.id for s in run(skaters(), lambda db: L.top_skaters(db, SEASON, 10, position="D"))] == [2]
    assert [s.player.id for s in run(skaters(), lambda db: L.top_skaters(db, SEASON, 10, position="F"))] == [1, 3]


def test_top_skaters_rejects_an_unknown_sort():
    with pytest.raises(ValueError):
        run(skaters(), lambda db: L.top_skaters(db, SEASON, 10, sort="hits"))


def goalies():
    return [
    player(11, pos="G"), player(12, pos="G"), player(13, pos="G"), player(14, pos="G", team=None), player(1),
    # G11: 2 games, 60 shots, 3 against on 7.0 expected -> .950, GAA 1.50, +4.0
    goalie_log(11, 101, 20261008, sog=30, ga=1, xga=3.5),
    goalie_log(11, 102, 20261009, sog=30, ga=2, xga=3.5),
    # G12: 3 games, 90 shots, 9 against on 9.9 expected -> .900, GAA 3.00, +0.9
    goalie_log(12, 101, 20261008, sog=30, ga=3, xga=3.3),
    goalie_log(12, 102, 20261009, sog=30, ga=3, xga=3.3),
    goalie_log(12, 103, 20261010, sog=30, ga=3, xga=3.3),
    # G13: one perfect game
    goalie_log(13, 101, 20261008, sog=20, ga=0, xga=1.5),
    goalie_log(14, 101, 20261008, sog=40, ga=0, xga=9.0),
    goalie_log(11, 50, 20251001, sog=50, ga=8, season=2025),
    ]


def test_top_goalies_works_out_the_rates_and_ranks_on_gsax():
    rows = run(goalies(), lambda db: L.top_goalies(db, SEASON, 10))
    assert [g.player.id for g in rows] == [11, 12]
    g11 = rows[0]
    assert (g11.games, g11.shots_faced, g11.goals_against, g11.high_danger_shots) == (2, 60, 3, 10)
    assert g11.save_percentage == pytest.approx(0.95)
    assert g11.gaa == pytest.approx(1.5)
    assert g11.gsax == pytest.approx(4.0)


def test_top_goalies_games_floor_and_the_other_sorts():
    ids = lambda rows: [g.player.id for g in rows]
    assert ids(run(goalies(), lambda db: L.top_goalies(db, SEASON, 10, min_games=1))) == [11, 13, 12]
    assert ids(run(goalies(), lambda db: L.top_goalies(db, SEASON, 10, min_games=3))) == [12]
    assert ids(run(goalies(), lambda db: L.top_goalies(db, SEASON, 10, "save_percentage", 1))) == [13, 11, 12]
    assert ids(run(goalies(), lambda db: L.top_goalies(db, SEASON, 10, "gaa", 1))) == [13, 11, 12]
    assert ids(run(goalies(), lambda db: L.top_goalies(db, SEASON, 10, "shots_faced", 1))) == [12, 11, 13]
    assert ids(run(goalies(), lambda db: L.top_goalies(db, SEASON, 1, "shots_faced", 1))) == [12]


def test_a_goalie_with_no_shots_ranks_last_on_the_rates():
    rows = [player(21, pos="G"), player(22, pos="G"),
            goalie_log(21, 101, 20261008, sog=0, ga=0, xga=0.0, toi=0.0),
            goalie_log(22, 101, 20261008, sog=10, ga=1, xga=0.5)]
    out = run(rows, lambda db: L.top_goalies(db, SEASON, 10, "save_percentage", 1))
    assert [g.player.id for g in out] == [22, 21]
    assert out[1].save_percentage is None and out[1].gaa is None


def test_season_through_reads_moneypucks_date():
    assert L.season_through(20261009) == datetime.date(2026, 10, 9)
    assert L.season_through(None) is None
    assert run(skaters(), lambda db: L.latest_game_date(db, SEASON)) == 20261010
