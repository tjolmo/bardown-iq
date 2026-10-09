"""Players with edge: the next slate's players whose props have at least one side with a positive edge."""
import asyncio
import datetime
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import edge_board as E
from app.models import Base, Games, Player, PlayerPropOdds, Props

NOW = datetime.datetime(2026, 10, 8, 21, 0, tzinfo=datetime.timezone.utc)
LATER = NOW + datetime.timedelta(hours=2)


def game(gid, date, start, state="FUT", home="TOR", away="MTL"):
    return Games(id=gid, home_team_tri_code=home, away_team_tri_code=away, season=20262027, date=date, venue="v",
                 start_time=start, game_state=state, last_updated=NOW)


def player(pid, team="TOR", pos="C"):
    return Player(id=pid, first_name=f"P{pid}", last_name="X", position=pos, current_team_tri_code=team,
                  last_updated=NOW)


def prop(gid, pid, side, odds, kind="player_points", line=0.5):
    return Props(game_id=gid, player_id=pid, prop_type=kind, over_under=side, odds=odds, line=line, book="fanduel")


def run(rows, now=NOW):
    async def go():
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            db.add_all(rows)
            await db.commit()
            return await E.build_board(db, now)
    return asyncio.run(go())


def fake_predictions(monkeypatch, skaters: dict, goalies: dict | None = None):
    async def skater(db, pid, team, game):
        return skaters.get(pid)
    async def goalie(db, pid, team, game):
        return (goalies or {}).get(pid)
    monkeypatch.setattr(E, "predict_skater", skater)
    monkeypatch.setattr(E, "predict_goalie", goalie)
    monkeypatch.setattr(E, "prop_dispersion", lambda: {})


GAME_IDS = (2026020101, 2026020102, 2026020103, 2026020104)


def test_keeps_players_with_a_positive_edge_best_first(monkeypatch):
    g = GAME_IDS[0]
    # P(points >= 1) = 1 - exp(-mu): 0.70 -> 0.503, 1.2 -> 0.699
    fake_predictions(monkeypatch, {1: {"points": 0.7}, 2: {"points": 1.2}, 3: {"points": 0.7}})
    board = run([game(g, 20261008, LATER), player(1), player(2), player(3, team="MTL"),
                 prop(g, 1, "Over", -110), prop(g, 1, "Under", -110),    # 0.503 / 0.497 at 1.909: both negative
                 prop(g, 2, "Over", -110), prop(g, 2, "Under", -110),    # over 0.699 * 1.909 - 1 = +33%
                 prop(g, 3, "Over", 120), prop(g, 3, "Under", -150)])     # over 0.503 * 2.2 - 1 = +10.7%
    assert board["game_date"] == 20261008 and board["players_priced"] == 3
    assert [p["player_id"] for p in board["players"]] == [2, 3]
    top = board["players"][0]
    assert top["opponent"] == "MTL" and top["home"] is True
    assert round(top["best_edge"], 3) == round(top["props"][0].edge, 3) and top["props"][0].over_under == "Over"
    # every priced prop comes along, edges first
    assert len(top["props"]) == 2 and top["props"][1].edge < 0
    assert board["players"][1]["opponent"] == "TOR" and board["players"][1]["home"] is False


def test_next_slate_skips_started_and_finished_games(monkeypatch):
    fake_predictions(monkeypatch, {1: {"points": 1.2}, 2: {"points": 1.2}, 3: {"points": 1.2}})
    started, finished, tonight, tomorrow = GAME_IDS
    board = run([game(started, 20261008, NOW - datetime.timedelta(minutes=5), "LIVE"),
                 game(finished, 20261008, NOW - datetime.timedelta(hours=4), "OFF", home="BOS", away="NYR"),
                 game(tonight, 20261008, LATER, home="EDM", away="CGY"),
                 game(tomorrow, 20261009, LATER + datetime.timedelta(days=1), home="VAN", away="SEA"),
                 player(1), player(2, team="EDM"), player(3, team="VAN"),
                 prop(started, 1, "Over", -110), prop(tonight, 2, "Over", -110), prop(tomorrow, 3, "Over", -110)])
    assert [p["player_id"] for p in board["players"]] == [2]


def test_espn_only_markets_count_and_backup_goalies_are_left_out(monkeypatch):
    g = GAME_IDS[0]
    fake_predictions(monkeypatch, {1: {"blocked_shots": 2.5}},
                     {5: {"saves": 30.0, "starting": False, "starter_status": "confirmed"},
                      6: {"saves": 30.0, "starting": True, "starter_status": "confirmed"}})
    board = run([game(g, 20261008, LATER), player(1, pos="D"), player(5, pos="G"), player(6, team="MTL", pos="G"),
                 PlayerPropOdds(game_id=g, player_id=1, prop_type="blocked_shots", line=1.5, book="DK",
                                espn_athlete_id=9, over_price=-110, under_price=-110, sides_inferred=False,
                                last_updated=NOW),
                 prop(g, 5, "Over", -110, "player_total_saves", 24.5), prop(g, 6, "Over", -110, "player_total_saves", 24.5)])
    ids = [p["player_id"] for p in board["players"]]
    assert ids == [6, 1] or ids == [1, 6]
    assert board["players_priced"] == 2
    goalie = next(p for p in board["players"] if p["player_id"] == 6)
    assert goalie["starter_status"] == "confirmed" and goalie["props"][0].source == "propline"


def test_empty_without_upcoming_games(monkeypatch):
    fake_predictions(monkeypatch, {})
    board = run([])
    assert board["game_date"] is None and board["players"] == []
