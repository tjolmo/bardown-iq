import asyncio
import datetime
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from external.nhl import games as games_module
from external.nhl.games import live_poll_minutes, parse_live_status
from app.game_board import format_clock, game_edge, live_out, needs_live_status
from app.schemas.teams import TeamMoneylineOut

FETCHED = datetime.datetime(2026, 10, 10, 1, 30, tzinfo=datetime.timezone.utc)


def feed_game(game_id=2026020101, state="LIVE", period=2, period_type="REG", seconds=494, running=True,
              intermission=False, home=1, away=0):
    return {"id": game_id, "gameType": 2, "gameState": state,
            "homeTeam": {"abbrev": "DAL", "score": home}, "awayTeam": {"abbrev": "CHI", "score": away},
            "period": period, "periodDescriptor": {"number": period, "periodType": period_type},
            "clock": {"timeRemaining": format_clock(seconds), "secondsRemaining": seconds,
                      "running": running, "inIntermission": intermission}}


def test_live_game_keeps_the_clock_as_reported():
    s = parse_live_status(feed_game(), FETCHED, now=FETCHED + datetime.timedelta(minutes=7))
    assert (s.game_state, s.period, s.period_type, s.seconds_remaining) == ("LIVE", 2, "REG", 494)
    assert (s.home_score, s.away_score, s.in_intermission, s.clock_running) == (1, 0, False, True)
    assert live_out(s).timeRemaining == "08:14"


def test_intermission_counts_down_from_the_fetch():
    game = feed_game(seconds=1080, running=True, intermission=True)
    s = parse_live_status(game, FETCHED, now=FETCHED + datetime.timedelta(minutes=5, seconds=55))
    assert s.in_intermission and s.seconds_remaining == 1080 - 355
    assert live_out(s).timeRemaining == "12:05"
    # never below zero when the next poll is late
    late = parse_live_status(game, FETCHED, now=FETCHED + datetime.timedelta(minutes=40))
    assert late.seconds_remaining == 0


def test_final_keeps_how_it_ended_and_drops_the_clock():
    s = parse_live_status(feed_game(state="OFF", period=4, period_type="OT", seconds=0, running=False,
                                    intermission=True), FETCHED)
    assert (s.game_state, s.period_type, s.seconds_remaining, s.in_intermission, s.clock_running) == \
        ("OFF", "OT", None, False, False)


@pytest.mark.parametrize("state", ["FUT", "PRE"])
def test_unstarted_games_have_no_status(state):
    assert parse_live_status(feed_game(state=state), FETCHED) is None


@pytest.mark.parametrize("raw, expected", [(None, 10), ("", 10), ("2", 2), ("0.5", 0.5), ("0", 10), ("-3", 10),
                                           ("soon", 10)])
def test_poll_minutes_from_env(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("LIVE_SCORES_POLL_MINUTES", raising=False)
    else:
        monkeypatch.setenv("LIVE_SCORES_POLL_MINUTES", raw)
    assert live_poll_minutes() == expected


def test_live_statuses_reuse_the_feed_within_the_poll_interval(monkeypatch):
    calls = []

    async def fake_fetch():
        calls.append(1)
        return True, [feed_game(), feed_game(game_id=2026020102, state="FUT")]

    monkeypatch.setattr(games_module, "_fetch_score_now", fake_fetch)
    monkeypatch.setattr(games_module, "_score_cache", None)
    monkeypatch.setenv("LIVE_SCORES_POLL_MINUTES", "10")
    first = asyncio.run(games_module.get_live_statuses())
    second = asyncio.run(games_module.get_live_statuses())
    assert list(first) == [2026020101] and list(second) == [2026020101]
    assert len(calls) == 1
    # the scheduled job always fetches fresh
    asyncio.run(games_module.get_current_scores())
    assert len(calls) == 2


def test_live_statuses_empty_when_the_feed_fails(monkeypatch):
    async def failing_fetch():
        return False, None

    monkeypatch.setattr(games_module, "_fetch_score_now", failing_fetch)
    monkeypatch.setattr(games_module, "_score_cache", None)
    assert asyncio.run(games_module.get_live_statuses()) == {}


def test_needs_live_status_from_shortly_before_puck_drop():
    now = FETCHED
    later = SimpleNamespace(start_time=now + datetime.timedelta(hours=2))
    soon = SimpleNamespace(start_time=now + datetime.timedelta(minutes=5))
    assert not needs_live_status([later], now)
    assert needs_live_status([later, soon], now)


def test_edge_is_the_model_minus_the_no_vig_price():
    # EDM +100 / VGK -120: no-vig VGK 0.5217, EDM 0.4783; model EDM 0.55
    edge = game_edge("VGK", "EDM", 0.45, 0.55, TeamMoneylineOut(home=-120, away=100))
    assert (edge.tri_code, edge.side, edge.points) == ("EDM", "away", 7.2)
    home = game_edge("DAL", "CHI", 0.72, 0.28, TeamMoneylineOut(home=-250, away=210))
    assert (home.tri_code, home.side, home.points) == ("DAL", "home", 3.1)


def test_no_edge_without_a_prediction_or_a_line():
    assert game_edge("VGK", "EDM", None, None, TeamMoneylineOut(home=-120, away=100)) is None
    assert game_edge("VGK", "EDM", 0.45, 0.55, None) is None
