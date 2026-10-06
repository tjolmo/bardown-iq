import asyncio
import datetime
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from external.odds_api import player_props as mod


def run_with_transport(monkeypatch, handler, coro_fn):
    monkeypatch.setenv("ODDS_API_KEY", "k")
    real = httpx.AsyncClient
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda: real(transport=httpx.MockTransport(handler)))
    return asyncio.run(coro_fn())


def events_call():
    now = datetime.datetime.now(datetime.timezone.utc)
    return mod.get_upcoming_games_odds_api(now, now + datetime.timedelta(days=1))


def test_quota_error_returns_empty_list_instead_of_typeerror(monkeypatch):
    handler = lambda r: httpx.Response(429, json={"message": "usage quota exceeded"})
    assert run_with_transport(monkeypatch, handler, events_call) == []


def test_invalid_key_dict_body_on_200_is_ignored(monkeypatch):
    handler = lambda r: httpx.Response(200, json={"message": "weird"})
    assert run_with_transport(monkeypatch, handler, events_call) == []


def test_props_error_returns_empty(monkeypatch):
    handler = lambda r: httpx.Response(401, json={"message": "invalid key"})
    assert run_with_transport(monkeypatch, handler, lambda: mod.get_player_props("e1")) == []


def test_missing_key_skips_request(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    assert asyncio.run(events_call()) == []


def test_events_parse_and_skip_malformed():
    out = mod.parse_events([
        {"id": "a", "home_team": "Montreal Canadiens", "away_team": "X", "commence_time": "2026-10-07T23:00:00Z"},
        {"id": "b"},
    ])
    assert [e.event_id for e in out] == ["a"]


def test_props_parse_skips_missing_description_and_price():
    payload = {"bookmakers": [{"markets": [{"key": "player_points", "outcomes": [
        {"name": "Over", "point": 0.5, "price": -120, "description": "Nick Suzuki"},
        {"name": "Over", "point": 0.5, "price": -120},
        {"name": "Over", "point": 0.5, "description": "Cole Caufield"},
    ]}]}]}
    out = mod.parse_player_props(payload)
    assert [(p.first_name, p.last_name) for p in out] == [("Nick", "Suzuki")]
