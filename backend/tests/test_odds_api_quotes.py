import asyncio
import datetime
import json
import os
import sys
from types import SimpleNamespace as NS

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.dialects import postgresql

from app import schedules
from app.crud.odds_api_prop_quotes import build_quote_rows, quote_upsert_stmt
from external.odds_api.player_props import parse_player_props, parse_events

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "odds_api", "event_props_synthetic.json")
NOW = datetime.datetime(2026, 10, 7, 20, 0, tzinfo=datetime.timezone.utc)


def load():
    with open(FIXTURE) as f:
        return json.load(f)


def test_parse_keeps_bookmaker_and_update_time():
    props = parse_player_props(load())
    # 9 complete outcomes; the BetMGM outcome without a price is dropped
    assert len(props) == 9
    assert {p.bookmaker for p in props} == {"draftkings", "fanduel", "betmgm"}
    dk = next(p for p in props if p.bookmaker == "draftkings" and p.prop_type == "player_points" and p.over_under == "Over")
    assert (dk.odds, dk.line, dk.first_name, dk.last_name) == (-150, 0.5, "Auston", "Matthews")
    assert dk.book_last_update == datetime.datetime(2026, 10, 7, 17, 59, tzinfo=datetime.timezone.utc)
    # market without its own last_update falls back to the bookmaker's
    mgm = next(p for p in props if p.bookmaker == "betmgm")
    assert mgm.book_last_update.minute == 2


def quote(**kw):
    base = dict(game_id=1, player_id=8, prop_type="player_points", over_under="Over", line=0.5, odds=-110, bookmaker="dk")
    return {**base, **kw}


def test_build_rows_dedupes_per_key_and_drops_bookless():
    rows = build_quote_rows([quote(odds=-110), quote(odds=-120), quote(bookmaker="fd"), quote(line=1.5),
                             quote(bookmaker=None)], NOW)
    assert len(rows) == 3
    dk = next(r for r in rows if r["bookmaker"] == "dk" and r["line"] == 0.5)
    assert dk["odds"] == dk["first_odds"] == -120
    assert dk["first_seen"] == dk["last_seen"] == NOW


def test_upsert_keeps_first_seen_price():
    sql = str(quote_upsert_stmt(build_quote_rows([quote()], NOW)).compile(dialect=postgresql.dialect()))
    conflict = sql.split("ON CONFLICT")[1]
    assert "(game_id, player_id, prop_type, over_under, line, bookmaker)" in conflict
    update = conflict.split("DO UPDATE SET")[1]
    assert "odds = excluded.odds" in update and "last_seen = excluded.last_seen" in update
    assert "first_odds" not in update and "first_seen" not in update


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def rollback(self):
        pass


def test_fetch_current_player_props_stores_every_quote_and_best_props(monkeypatch):
    payload = load()
    events = parse_events([payload])
    matthews = NS(id=8479318, first_name="Auston", last_name="Matthews", position="C")
    captured = {}

    async def fake_events(start, end):
        return events

    async def fake_games(db, date):
        return [NS(id=2026020001, home_team_tri_code="TOR", away_team_tri_code="MTL")]

    async def fake_teams(db):
        return [NS(current_name="Toronto Maple Leafs", tri_code="TOR"), NS(current_name="Montreal Canadiens", tri_code="MTL")]

    async def fake_props(event_id):
        assert event_id == "evt123"
        return parse_player_props(payload)

    async def fake_players(db, codes):
        return [matthews]

    async def fake_upsert_props(db, props):
        captured["props"] = props

    async def fake_upsert_quotes(db, quotes):
        captured["quotes"] = quotes

    monkeypatch.setattr(schedules, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(schedules, "get_upcoming_games_odds_api", fake_events)
    monkeypatch.setattr(schedules, "get_all_games_for_date", fake_games)
    monkeypatch.setattr(schedules, "get_all_teams", fake_teams)
    monkeypatch.setattr(schedules, "get_player_props", fake_props)
    monkeypatch.setattr(schedules, "get_players_on_teams", fake_players)
    monkeypatch.setattr(schedules, "upsert_player_props", fake_upsert_props)
    monkeypatch.setattr(schedules, "upsert_odds_api_prop_quotes", fake_upsert_quotes)

    asyncio.run(schedules.fetch_current_player_props())

    quotes = captured["quotes"]
    # every matched quote from every book (the unknown skater is not matched)
    assert len(quotes) == 8
    assert {q["bookmaker"] for q in quotes} == {"draftkings", "fanduel", "betmgm"}
    assert all(q["game_id"] == 2026020001 and q["player_id"] == matthews.id and q["event_id"] == "evt123" for q in quotes)
    # the props table still gets one row per side at the consensus line with the best price
    best = {(p.prop_type, p.over_under): (p.line, p.odds) for p in captured["props"]}
    assert best[("player_points", "Over")] == (0.5, -140)
    assert best[("player_points", "Under")] == (0.5, 120)
    assert best[("player_goals", "Over")] == (0.5, 110)
