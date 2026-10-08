"""The player page's prop board: PropLine best prices (with every book's price) plus ESPN markets (hits) PropLine
doesn't carry."""
import asyncio
import datetime
import os
import sys
from types import SimpleNamespace as NS

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.crud import props as C
from app.models import Base, Games, Player, PlayerPropOdds, PropQuote, Props
from app.schemas.player import PlayerPropOut

NOW = datetime.datetime(2026, 10, 8, 21, 0, tzinfo=datetime.timezone.utc)


def run(coro_fn):
    async def go():
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return await coro_fn(db)
    return asyncio.run(go())


def espn(gid, prop, line, over, under, pid=1, book="Draft Kings"):
    return PlayerPropOdds(game_id=gid, player_id=pid, prop_type=prop, line=line, book=book, espn_athlete_id=9,
                          over_price=over, under_price=under, sides_inferred=True, last_updated=NOW)


def test_props_upsert_ignores_output_only_fields():
    # PlayerPropOut carries model_prob / edge / source / other_books for the API; the props table has none of them
    prop = PlayerPropOut(game_id=1, player_id=1, prop_type="player_points", over_under="Over", odds=-110, line=0.5,
                         model_prob=0.5, edge=0.01, source="propline", book="fanduel")
    sql = str(C.props_upsert_stmt([prop]).compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT" in sql and "model_prob" not in sql and "source" not in sql and "other_books" not in sql
    assert "book = excluded.book" in sql


def test_espn_rows_fill_markets_propline_missed():
    markets = [NS(game_id=1, player_id=1, prop_type="hits", line=2.5, over_price=-105, under_price=-125, book="DK"),
               NS(game_id=1, player_id=1, prop_type="points", line=0.5, over_price=-150, under_price=120, book="DK"),
               NS(game_id=1, player_id=1, prop_type="blocked_shots", line=1.5, over_price=110, under_price=None, book="DK"),
               NS(game_id=1, player_id=1, prop_type="anytime_goal", line=0.5, over_price=240, under_price=None, book="DK"),
               NS(game_id=1, player_id=1, prop_type="points_milestone", line=1.5, over_price=300, under_price=None, book="DK")]
    rows = C.espn_prop_rows(markets, covered={"player_points"})
    assert [(r.prop_type, r.over_under, r.odds) for r in rows] == [
        ("player_goal_scorer_anytime", "Yes", 240), ("player_hits", "Over", -105), ("player_hits", "Under", -125)]
    assert all(r.source == "espn" and r.book == "DK" for r in rows)


def test_board_merges_latest_game_and_router_prices_hits(monkeypatch):
    from app.routers import player_router as R

    async def fake_predict_skater(db, pid, team, game):
        return {"goals": 0.3, "points": 0.7, "hits": 2.4}
    monkeypatch.setattr(R, "predict_skater", fake_predict_skater)

    async def go(db):
        db.add(Player(id=1, first_name="A", last_name="S", position="C", current_team_tri_code="TOR", last_updated=NOW))
        db.add(Games(id=2, home_team_tri_code="TOR", away_team_tri_code="MTL", season=20262027, date=20261008,
                     venue="v", start_time=NOW, game_state="FUT", last_updated=NOW))
        db.add_all([Props(game_id=1, player_id=1, prop_type="player_points", over_under="Over", odds=-130, line=0.5),
                    Props(game_id=2, player_id=1, prop_type="player_points", over_under="Over", odds=-120, line=0.5),
                    Props(game_id=2, player_id=1, prop_type="player_points", over_under="Under", odds=100, line=0.5),
                    espn(2, "points", 0.5, -150, 120), espn(2, "hits", 2.5, -105, -125), espn(1, "hits", 1.5, 100, -120)])
        await db.commit()
        return await R.get_player_props(1, db)
    out = run(go)
    by = {(p.prop_type, p.over_under): p for p in out}
    # game 2 only; ESPN's points market is left out (PropLine priced points), its hits are added
    assert set(by) == {("player_points", "Over"), ("player_points", "Under"), ("player_hits", "Over"), ("player_hits", "Under")}
    assert by[("player_points", "Over")].source == "propline" and by[("player_hits", "Over")].source == "espn"
    hits = by[("player_hits", "Over")]
    # negative binomial pricing (alpha 0.12) from the model's 2.4 expected hits, and the return at -105
    from predictions.predict import prop_probability
    assert hits.model_prob == pytest.approx(prop_probability({"hits": 2.4}, "player_hits", 2.5, "Over"), abs=1e-4)
    assert hits.edge == pytest.approx(hits.model_prob * (1 + 100 / 105) - 1, abs=1e-3)
    assert by[("player_hits", "Over")].model_prob + by[("player_hits", "Under")].model_prob == pytest.approx(1, abs=1e-3)


def test_board_shows_espn_only_game():
    async def go(db):
        db.add(espn(5, "blocked_shots", 1.5, 120, -150))
        await db.commit()
        return await C.get_player_prop_board(db, 1), await C.get_player_prop_board(db, 2)
    rows, none = run(go)
    assert [(r.prop_type, r.over_under) for r in rows] == [("player_blocked_shots", "Over"), ("player_blocked_shots", "Under")]
    assert none == []


def pq(side, odds, book, line=0.5, seen=NOW):
    return PropQuote(game_id=2, player_id=1, prop_type="player_points", over_under=side, line=line, bookmaker=book,
                     odds=odds, first_odds=odds, first_seen=seen, last_seen=seen, provider="propline")


def test_board_lists_other_books_from_latest_fetch():
    async def go(db):
        db.add(Props(game_id=2, player_id=1, prop_type="player_points", over_under="Over", odds=-110, line=0.5,
                     book="fanduel"))
        db.add_all([pq("Over", -110, "fanduel"), pq("Over", -125, "draftkings"), pq("Over", 105, "bovada"),
                    pq("Over", 260, "draftkings", line=1.5), pq("Under", -105, "draftkings"),
                    # pulled before the latest fetch: not listed
                    pq("Over", -100, "betrivers", seen=NOW - datetime.timedelta(hours=3))])
        await db.commit()
        return await C.get_player_prop_board(db, 1)
    (row,) = run(go)
    assert row.book == "fanduel" and row.source == "propline"
    # the shown price is left out; same line first (best first), then other lines; Bovada is flagged
    assert [(b.book, b.line, b.odds, b.consensus) for b in row.other_books] == [
        ("bovada", 0.5, 105, False), ("draftkings", 0.5, -125, True), ("draftkings", 1.5, 260, True)]
