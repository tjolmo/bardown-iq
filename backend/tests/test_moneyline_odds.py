import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from external.nhl import games as games_module


def odds(value, description="MONEY_LINE_2_WAY_TNB"):
    return {"description": description, "value": value}


def make_game(game_id, home=None, away=None):
    return {
        "gameId": game_id,
        "homeTeam": {"odds": [odds(home)] if home is not None else [odds(1.5, "PUCK_LINE")]},
        "awayTeam": {"odds": [odds(away)] if away is not None else []},
    }


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture
def fake_api(monkeypatch):
    state = {"calls": 0, "payload": {"games": []}, "fail": False}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            state["calls"] += 1
            if state["fail"]:
                raise RuntimeError("boom")
            return FakeResponse(state["payload"])

    monkeypatch.setattr(games_module.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(games_module, "_odds_cache", None)
    return state


def test_game_without_moneyline_does_not_crash_or_inherit(fake_api):
    fake_api["payload"] = {"games": [make_game(1), make_game(2, "-150", "+130"), make_game(3)]}
    result = asyncio.run(games_module.get_odds_for_current_games())
    assert [(o.game_id, o.home_moneyline, o.away_moneyline) for o in result] == [(2, -150, 130)]


def test_result_is_cached(fake_api):
    fake_api["payload"] = {"games": [make_game(1, "-150", "+130")]}

    async def go():
        await games_module.get_odds_for_current_games()
        return await games_module.get_odds_for_current_games()

    result = asyncio.run(go())
    assert fake_api["calls"] == 1
    assert len(result) == 1


def test_cache_expires(fake_api, monkeypatch):
    fake_api["payload"] = {"games": [make_game(1, "-150", "+130")]}
    clock = {"now": 1000.0}
    monkeypatch.setattr(games_module.time, "monotonic", lambda: clock["now"])

    async def go():
        await games_module.get_odds_for_current_games()
        clock["now"] += games_module.ODDS_CACHE_TTL_SECONDS + 1
        await games_module.get_odds_for_current_games()

    asyncio.run(go())
    assert fake_api["calls"] == 2


def test_failures_are_not_cached(fake_api):
    fake_api["fail"] = True

    async def go():
        first = await games_module.get_odds_for_current_games()
        fake_api["fail"] = False
        fake_api["payload"] = {"games": [make_game(1, "-150", "+130")]}
        return first, await games_module.get_odds_for_current_games()

    first, second = asyncio.run(go())
    assert first is None
    assert len(second) == 1
    assert fake_api["calls"] == 2
