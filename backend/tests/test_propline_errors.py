import asyncio
import datetime
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from external.propline import client as mod


def run_with_transport(monkeypatch, handler, coro_fn):
    monkeypatch.setenv("PROPLINE_API_KEY", "k")
    real = httpx.AsyncClient
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda: real(transport=httpx.MockTransport(handler)))
    return asyncio.run(coro_fn())


def events_call():
    now = datetime.datetime.now(datetime.timezone.utc)
    return mod.get_upcoming_games(now, now + datetime.timedelta(days=1))


def test_quota_error_returns_empty_list_instead_of_typeerror(monkeypatch):
    handler = lambda r: httpx.Response(429, json={"detail": {"error": "daily_limit_exceeded"}})
    assert run_with_transport(monkeypatch, handler, events_call) == []


def test_dict_body_on_200_is_ignored(monkeypatch):
    handler = lambda r: httpx.Response(200, json={"message": "weird"})
    assert run_with_transport(monkeypatch, handler, events_call) == []


def test_props_error_returns_empty(monkeypatch):
    handler = lambda r: httpx.Response(401, json={"detail": {"error": "invalid_api_key"}})
    assert run_with_transport(monkeypatch, handler, lambda: mod.get_player_props("e1")) == []


def test_game_lines_error_returns_empty(monkeypatch):
    handler = lambda r: httpx.Response(429, json={"detail": {"error": "daily_limit_exceeded"}})
    assert run_with_transport(monkeypatch, handler, mod.get_game_lines) == []


def test_missing_key_skips_request(monkeypatch):
    monkeypatch.delenv("PROPLINE_API_KEY", raising=False)
    assert asyncio.run(events_call()) == []
    assert asyncio.run(mod.get_event_odds("e1")) is None


def test_key_sent_as_header_and_events_filtered_to_window(monkeypatch):
    now = datetime.datetime.now(datetime.timezone.utc)
    soon, later = now + datetime.timedelta(hours=3), now + datetime.timedelta(days=3)
    seen = {}

    def handler(request):
        seen["key"] = request.headers.get("x-api-key")
        seen["query"] = dict(request.url.params)
        return httpx.Response(200, json=[
            {"id": 1, "home_team": "A", "away_team": "B", "commence_time": soon.isoformat()},
            {"id": 2, "home_team": "C", "away_team": "D", "commence_time": later.isoformat()},
        ])
    out = run_with_transport(monkeypatch, handler, events_call)
    # integer ids come back as strings; the key never goes in the URL
    assert [e.event_id for e in out] == ["1"] and seen["key"] == "k" and "apiKey" not in seen["query"]


def test_event_odds_requests_listed_markets_and_books(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/markets"):
            return httpx.Response(200, json={"markets": [{"key": "player_points", "count": 4},
                                                         {"key": "goalie_saves", "count": 2},
                                                         {"key": "player_hits", "count": 1}]})
        return httpx.Response(200, json={"id": "e1", "bookmakers": []})
    run_with_transport(monkeypatch, handler, lambda: mod.get_event_odds("e1"))
    params = calls[-1].url.params
    assert params["markets"] == "h2h,spreads,totals,goalie_saves,player_hits,player_points"
    assert "draftkings" in params["bookmakers"] and "prizepicks" not in params["bookmakers"]


def test_event_odds_falls_back_to_documented_markets(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/markets"):
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, json={"id": "e1", "bookmakers": []})
    run_with_transport(monkeypatch, handler, lambda: mod.get_event_odds("e1"))
    assert calls[-1].url.params["markets"] == "h2h,spreads,totals," + ",".join(mod.DOCUMENTED_PROP_MARKETS)


def test_events_parse_and_skip_malformed():
    out = mod.parse_events([
        {"id": "a", "home_team": "Montreal Canadiens", "away_team": "X", "commence_time": "2026-10-07T23:00:00Z"},
        {"id": "b"},
    ])
    assert [e.event_id for e in out] == ["a"]


def test_props_parse_skips_missing_description_and_price():
    payload = {"bookmakers": [{"key": "fanduel", "markets": [{"key": "player_points", "outcomes": [
        {"name": "Over", "point": 0.5, "price": -120, "description": "Nick Suzuki"},
        {"name": "Over", "point": 0.5, "price": -120},
        {"name": "Over", "point": 0.5, "description": "Cole Caufield"},
    ]}]}]}
    out = mod.parse_player_props(payload)
    assert [(p.first_name, p.last_name) for p in out] == [("Nick", "Suzuki")]


def test_props_parse_live_shapes():
    # shapes seen live (Oct 2026): anytime-goalscorer lists named after the player, "N+" rungs under the base key,
    # Bovada's team suffix
    def mk(book, key, line_type, outcomes):
        return {"key": book, "markets": [{"key": key, "line_type": line_type, "outcomes": outcomes}]}
    payload = {"bookmakers": [
        mk("draftkings", "player_goals", "main", [
            {"name": "Adam Lowry", "description": "Adam Lowry", "price": 550, "point": None, "player_id": "nhl:8476392"}]),
        mk("fanduel", "player_assists", "milestone", [
            {"name": "1+ Assists", "description": "Cale Makar", "price": -186, "point": None},
            {"name": "2+ Assists", "description": "Cale Makar", "price": 400, "point": None}]),
        mk("bovada", "goalie_saves", "main", [
            {"name": "Over", "description": "Mackenzie Blackwood (COL)", "price": -125, "point": 23.5}]),
        mk("betrivers", "player_assists", "main", [
            {"name": "No", "description": "Artturi Lehkonen", "price": -220, "point": None}]),
        # a 1+ shots rung is not the shots market (line 2.5): skipped
        mk("draftkings", "player_shots_on_goal", "milestone", [
            {"name": "1+ Shots on Goal", "description": "Cale Makar", "price": -1600, "point": None}]),
    ]}
    got = [(p.bookmaker, p.prop_type, p.first_name, p.last_name, p.over_under, p.line, p.odds, p.nhl_player_id)
           for p in mod.parse_player_props(payload)]
    assert got == [
        ("draftkings", "player_goals", "Adam", "Lowry", "Over", 0.5, 550, 8476392),
        ("fanduel", "player_assists", "Cale", "Makar", "Over", 0.5, -186, None),
        ("bovada", "player_total_saves", "Mackenzie", "Blackwood", "Over", 23.5, -125, None),
        ("betrivers", "player_assists", "Artturi", "Lehkonen", "Under", 0.5, -220, None),
    ]


def test_game_lines_skip_three_way_moneyline():
    payload = {"id": "211514", "home_team": "Winnipeg Jets", "away_team": "Colorado Avalanche", "bookmakers": [
        {"key": "bovada", "markets": [
            {"key": "h2h", "line_type": "main", "description": "Moneyline", "outcomes": [
                {"name": "Winnipeg Jets", "price": 163, "side": "home"},
                {"name": "Colorado Avalanche", "price": -190, "side": "away"}]},
            {"key": "h2h", "line_type": "main", "description": "3-Way Moneyline", "outcomes": [
                {"name": "Winnipeg Jets", "price": 235, "side": "home"},
                {"name": "Colorado Avalanche", "price": -120, "side": "away"},
                {"name": "Tie", "price": 335, "side": "draw"}]},
        ]}]}
    assert [(l.side, l.odds) for l in mod.parse_game_lines(payload)] == [("home", 163), ("away", -190)]
