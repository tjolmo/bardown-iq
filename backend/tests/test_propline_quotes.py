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
from app.crud.prop_quotes import build_quote_rows, quote_upsert_stmt
from app.crud.game_line_quotes import build_line_rows, summarize_moneylines
from external.propline.client import parse_events, parse_game_lines, parse_player_props

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "propline", "event_odds_synthetic.json")
NOW = datetime.datetime(2026, 10, 7, 20, 0, tzinfo=datetime.timezone.utc)


def load():
    with open(FIXTURE) as f:
        return json.load(f)


def test_parse_maps_markets_and_skips_what_the_app_does_not_use():
    props = parse_player_props(load())
    # 12 usable outcomes: alternate lines, the 2+ rung, a suspended market, a priceless outcome and a book's frozen
    # in-play quote (pregame_only) are dropped
    assert len(props) == 12
    assert {p.bookmaker for p in props} == {"draftkings", "fanduel", "betrivers", "bovada"}
    dk = next(p for p in props if p.bookmaker == "draftkings" and p.prop_type == "player_points" and p.over_under == "Over")
    assert (dk.odds, dk.line, dk.first_name, dk.last_name, dk.nhl_player_id) == (-150, 0.5, "Auston", "Matthews", 8479318)
    # the outcome's own update time wins over the market's
    assert dk.book_last_update == datetime.datetime(2026, 10, 7, 17, 59, tzinfo=datetime.timezone.utc)
    # goalie_saves -> the app's player_total_saves; the 1+ points rung -> points over 0.5
    saves = [p for p in props if p.prop_type == "player_total_saves"]
    assert {(p.over_under, p.line) for p in saves} == {("Over", 26.5), ("Under", 26.5)}
    rung = next(p for p in props if p.bookmaker == "betrivers")
    assert (rung.prop_type, rung.over_under, rung.line, rung.odds) == ("player_points", "Over", 0.5, -145)
    assert not any(p.line == 1.5 for p in props if p.prop_type == "player_points")
    assert [(p.bookmaker, p.line) for p in props if p.prop_type == "player_hits"] == [("betrivers", 1.5)]


def test_parse_game_lines_sides_and_lines():
    lines = parse_game_lines(load())
    got = {(l.bookmaker, l.market, l.side): (l.line, l.odds) for l in lines}
    assert len(lines) == 10
    # book spellings ("Montreal", "MTL Canadiens") resolve to the event's sides
    assert got[("draftkings", "h2h", "away")] == (0.0, 135) and got[("bovada", "h2h", "away")] == (0.0, 140)
    assert got[("fanduel", "h2h", "home")] == (0.0, -155)
    assert got[("draftkings", "spreads", "home")] == (-1.5, 150) and got[("draftkings", "spreads", "away")] == (1.5, -180)
    # the team total is skipped; the game total kept
    assert got[("draftkings", "totals", "over")] == (6.5, -110)
    assert not any(l.bookmaker == "pinnacle" for l in lines)
    assert {l.event_id for l in lines} == {"9001"}


def test_moneyline_summary_medians_consensus_books_and_finds_best():
    seen = NOW
    rows = build_line_rows([{"game_id": 1, "market": l.market, "side": l.side, "line": l.line, "odds": l.odds,
                             "bookmaker": l.bookmaker} for l in parse_game_lines(load())], seen)
    ml = summarize_moneylines([NS(**r) for r in rows])[1]
    # median of DraftKings and FanDuel (Bovada is not a consensus book), on implied probability
    assert ml["home"] == -157 and ml["away"] == 132 and ml["n_books"] == 2
    # best price per side among the consensus books
    assert (ml["best_home"], ml["best_home_book"]) == (-155, "fanduel")
    assert (ml["best_away"], ml["best_away_book"]) == (135, "draftkings")
    # a later fetch supersedes: books missing from it drop out
    later = [NS(**{**r, "last_seen": NOW + datetime.timedelta(hours=1)}) for r in rows if r["bookmaker"] == "draftkings"]
    stale = [NS(**r) for r in rows if r["bookmaker"] != "draftkings"]
    ml = summarize_moneylines(later + stale)[1]
    assert (ml["home"], ml["away"], ml["n_books"]) == (-160, 135, 1)


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
    # Matthews is matched by PropLine's NHL id even though the stored name differs
    matthews = NS(id=8479318, first_name="Auston", last_name="Matthews-X", position="C")
    woll = NS(id=8479361, first_name="Joseph", last_name="Woll", position="G")
    captured = {}

    async def fake_events(start, end):
        return events

    async def fake_games(db, date):
        return [NS(id=2026020001, home_team_tri_code="TOR", away_team_tri_code="MTL", start_time=events[0].commence_time)]

    async def fake_teams(db):
        return [NS(current_name="Toronto Maple Leafs", tri_code="TOR"), NS(current_name="Montreal Canadiens", tri_code="MTL")]

    async def fake_odds(event_id):
        assert event_id == "9001"
        return payload

    async def fake_players(db, codes):
        return [matthews, woll]

    async def fake_upsert_props(db, props):
        captured["props"] = props

    async def fake_upsert_quotes(db, quotes):
        captured["quotes"] = quotes

    async def fake_upsert_lines(db, rows):
        captured["lines"] = rows

    monkeypatch.setattr(schedules, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(schedules, "get_upcoming_games", fake_events)
    monkeypatch.setattr(schedules, "get_all_games_for_date", fake_games)
    monkeypatch.setattr(schedules, "get_all_teams", fake_teams)
    monkeypatch.setattr(schedules, "get_event_odds", fake_odds)
    monkeypatch.setattr(schedules, "get_players_on_teams", fake_players)
    monkeypatch.setattr(schedules, "upsert_player_props", fake_upsert_props)
    monkeypatch.setattr(schedules, "upsert_prop_quotes", fake_upsert_quotes)
    monkeypatch.setattr(schedules, "upsert_game_line_quotes", fake_upsert_lines)

    asyncio.run(schedules.fetch_current_player_props())

    quotes = captured["quotes"]
    # every matched quote from every book (the unknown skater is not matched)
    assert len(quotes) == 11
    assert {q["bookmaker"] for q in quotes} == {"draftkings", "fanduel", "betrivers", "bovada"}
    assert all(q["game_id"] == 2026020001 and q["event_id"] == "9001" for q in quotes)
    assert {q["player_id"] for q in quotes if q["prop_type"] == "player_total_saves"} == {woll.id}
    # the props table gets one row per side at the consensus line with the best consensus-book price and its book
    best = {(p.prop_type, p.over_under): (p.line, p.odds, p.book) for p in captured["props"]}
    assert best[("player_points", "Over")] == (0.5, -140, "fanduel")      # Bovada's -130 doesn't count
    assert best[("player_points", "Under")] == (0.5, 120, "draftkings")
    assert best[("player_goals", "Over")] == (0.5, 110, "draftkings")
    # the same request's game lines are stored for the game
    assert len(captured["lines"]) == 10 and {r["game_id"] for r in captured["lines"]} == {2026020001}
