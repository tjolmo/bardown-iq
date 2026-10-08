import asyncio
import datetime
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import main, schedules

MONDAY = datetime.datetime(2026, 10, 12, 3, tzinfo=datetime.timezone.utc)
TUESDAY = MONDAY + datetime.timedelta(days=1)


def test_weekly_is_the_default_and_trains_on_monday(monkeypatch):
    monkeypatch.delenv("TRAIN_SCHEDULE", raising=False)
    monkeypatch.delenv("TRAIN_WEEKDAY", raising=False)
    assert schedules.train_schedule() == "weekly"
    assert schedules.should_train_tonight(MONDAY)
    assert not schedules.should_train_tonight(TUESDAY)


def test_train_weekday_override(monkeypatch):
    monkeypatch.setenv("TRAIN_SCHEDULE", "weekly")
    monkeypatch.setenv("TRAIN_WEEKDAY", "1")
    assert schedules.should_train_tonight(TUESDAY)
    assert not schedules.should_train_tonight(MONDAY)


def test_nightly_off_and_unknown(monkeypatch):
    monkeypatch.setenv("TRAIN_SCHEDULE", "nightly")
    assert schedules.should_train_tonight(TUESDAY)
    monkeypatch.setenv("TRAIN_SCHEDULE", "off")
    assert not schedules.should_train_tonight(MONDAY)
    monkeypatch.setenv("TRAIN_SCHEDULE", "sometimes")
    assert schedules.train_schedule() == "weekly"


def _stub_nightly(monkeypatch, logs_ok=True, missing=False):
    calls = []
    async def ok():
        return None
    async def fail():
        raise RuntimeError("scrape failed")
    for name in ("fetch_current_schedules_for_all_teams", "fetch_current_rosters_for_all_teams", "scrape_team_stats",
                 "refresh_skater_shares", "fetch_recent_actual_starters", "fetch_recent_game_odds",
                 "fetch_recent_player_prop_odds", "score_logged_predictions", "fetch_current_player_props"):
        monkeypatch.setattr(schedules, name, ok)
    monkeypatch.setattr(schedules, "scrape_all_player_logs", ok if logs_ok else fail)
    async def train():
        calls.append("train")
    monkeypatch.setattr(schedules, "train_models", train)
    monkeypatch.setattr(schedules, "models_missing", lambda: missing)
    return calls


def test_nightly_skips_training_off_schedule(monkeypatch):
    calls = _stub_nightly(monkeypatch)
    monkeypatch.setattr(schedules, "should_train_tonight", lambda: False)
    asyncio.run(schedules.nightly_pipeline())
    assert calls == []


def test_nightly_trains_on_schedule_or_when_bundles_missing(monkeypatch):
    calls = _stub_nightly(monkeypatch)
    monkeypatch.setattr(schedules, "should_train_tonight", lambda: True)
    asyncio.run(schedules.nightly_pipeline())
    assert calls == ["train"]
    calls = _stub_nightly(monkeypatch, missing=True)
    monkeypatch.setattr(schedules, "should_train_tonight", lambda: False)
    asyncio.run(schedules.nightly_pipeline())
    assert calls == ["train"]


def test_nightly_never_trains_after_a_failed_scrape(monkeypatch):
    calls = _stub_nightly(monkeypatch, logs_ok=False, missing=True)
    monkeypatch.setattr(schedules, "should_train_tonight", lambda: True)
    asyncio.run(schedules.nightly_pipeline())
    assert calls == []


def test_missed_pregame_log_window():
    at = lambda h: datetime.datetime(2026, 10, 8, h, 30, tzinfo=datetime.timezone.utc)
    assert [h for h in range(24) if main.missed_pregame_log(at(h))] == [0, 1, 2, 3, 4, 5, 21, 22, 23]


def test_scheduler_enabled_flag(monkeypatch):
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    assert main.scheduler_enabled()
    for off in ("0", "false", "off"):
        monkeypatch.setenv("SCHEDULER_ENABLED", off)
        assert not main.scheduler_enabled()


def _stub_startup(monkeypatch, missing: bool, missed_log: bool):
    calls = []
    def step(name):
        async def run():
            calls.append(name)
        return run
    for name in ("add_current_teams_to_db", "add_old_teams_to_db", "fetch_current_schedules_for_all_teams",
                 "fetch_current_rosters_for_all_teams", "scrape_all_player_logs", "scrape_team_stats"):
        monkeypatch.setattr(main, name, step(name))
    monkeypatch.setattr(main, "train_models", step("train"))
    monkeypatch.setattr(main, "pregame_odds_pipeline", step("pregame"))
    monkeypatch.setattr(main, "models_missing", lambda: missing)
    monkeypatch.setattr(main, "missed_pregame_log", lambda: missed_log)
    return calls


def test_startup_trains_only_when_bundles_missing(monkeypatch):
    monkeypatch.delenv("TRAIN_ON_STARTUP", raising=False)
    calls = _stub_startup(monkeypatch, missing=False, missed_log=False)
    asyncio.run(main.run_startup_refresh())
    assert "train" not in calls and "pregame" not in calls
    calls = _stub_startup(monkeypatch, missing=True, missed_log=False)
    asyncio.run(main.run_startup_refresh())
    assert calls[-1] == "train"
    monkeypatch.setenv("TRAIN_ON_STARTUP", "always")
    calls = _stub_startup(monkeypatch, missing=False, missed_log=False)
    asyncio.run(main.run_startup_refresh())
    assert calls[-1] == "train"


def test_startup_catches_up_a_missed_pregame_log_first(monkeypatch):
    monkeypatch.delenv("TRAIN_ON_STARTUP", raising=False)
    calls = _stub_startup(monkeypatch, missing=False, missed_log=True)
    asyncio.run(main.run_startup_refresh())
    assert calls[0] == "pregame"
    # no bundles: nothing to log with
    calls = _stub_startup(monkeypatch, missing=True, missed_log=True)
    asyncio.run(main.run_startup_refresh())
    assert "pregame" not in calls
