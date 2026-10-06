import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from external.nhl import games as games_module


def make_game(game_id, game_type=2, home="TOR", away="MTL", **overrides):
    game = {
        "id": game_id,
        "gameType": game_type,
        "season": 20252026,
        "gameDate": "2025-10-08",
        "venue": {"default": "Scotiabank Arena"},
        "startTimeUTC": "2025-10-08T23:00:00Z",
        "gameState": "FUT",
        "homeTeam": {"abbrev": home, "logo": "h.svg", "score": 0},
        "awayTeam": {"abbrev": away, "logo": "a.svg", "score": 0},
    }
    game.update(overrides)
    return game


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def run(monkeypatch, games, valid_tri_codes=None):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            return FakeResponse({"games": games})

    monkeypatch.setattr(games_module.httpx, "AsyncClient", FakeClient)
    return asyncio.run(games_module.get_current_scores(valid_tri_codes))


def test_bad_game_is_skipped_not_fatal(monkeypatch):
    bad = make_game(2, venue=None)
    result = run(monkeypatch, [make_game(1), bad, make_game(3)])
    assert [g.id for g in result] == [1, 3]


def test_preseason_games_are_dropped(monkeypatch):
    result = run(monkeypatch, [make_game(1, game_type=1), make_game(2, game_type=3)])
    assert [g.id for g in result] == [2]


def test_unknown_teams_are_dropped(monkeypatch):
    foreign = make_game(2, home="ZZZ")
    result = run(monkeypatch, [make_game(1), foreign], {"TOR", "MTL"})
    assert [g.id for g in result] == [1]


def test_nothing_valid_returns_none(monkeypatch):
    assert run(monkeypatch, [make_game(1, game_type=1)]) is None
