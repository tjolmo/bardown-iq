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


def _stub_pipelines(monkeypatch, logs_ok=True, missing=False, before_slate=True):
    calls = []
    async def ok(*args):
        return None
    async def fail():
        raise RuntimeError("scrape failed")
    for name in ("fetch_current_schedules_for_all_teams", "fetch_current_rosters_for_all_teams", "scrape_team_stats",
                 "refresh_skater_shares", "fetch_recent_actual_starters", "fetch_recent_game_lineups",
                 "fetch_recent_game_odds", "fetch_recent_player_prop_odds", "score_logged_predictions",
                 "fetch_current_player_props"):
        monkeypatch.setattr(schedules, name, ok)
    monkeypatch.setattr(schedules, "scrape_all_player_logs", ok if logs_ok else fail)
    async def train():
        calls.append("train")
    monkeypatch.setattr(schedules, "train_models", train)
    monkeypatch.setattr(schedules, "models_missing", lambda: missing)
    monkeypatch.setattr(schedules, "before_slate", lambda: before_slate)
    return calls


def test_nightly_never_trains(monkeypatch):
    calls = _stub_pipelines(monkeypatch, missing=True)
    monkeypatch.setattr(schedules, "should_train_tonight", lambda: True)
    asyncio.run(schedules.nightly_pipeline())
    assert calls == []


def test_catchup_skips_training_off_schedule(monkeypatch):
    calls = _stub_pipelines(monkeypatch)
    monkeypatch.setattr(schedules, "should_train_tonight", lambda: False)
    asyncio.run(schedules.catchup_pipeline())
    assert calls == []


def test_catchup_trains_on_schedule_or_when_bundles_missing(monkeypatch):
    calls = _stub_pipelines(monkeypatch)
    monkeypatch.setattr(schedules, "should_train_tonight", lambda: True)
    asyncio.run(schedules.catchup_pipeline())
    assert calls == ["train"]
    calls = _stub_pipelines(monkeypatch, missing=True)
    monkeypatch.setattr(schedules, "should_train_tonight", lambda: False)
    asyncio.run(schedules.catchup_pipeline())
    assert calls == ["train"]


def test_catchup_never_trains_after_a_failed_scrape_or_during_the_slate(monkeypatch):
    calls = _stub_pipelines(monkeypatch, logs_ok=False, missing=True)
    monkeypatch.setattr(schedules, "should_train_tonight", lambda: True)
    asyncio.run(schedules.catchup_pipeline())
    assert calls == []
    calls = _stub_pipelines(monkeypatch, before_slate=False)
    asyncio.run(schedules.catchup_pipeline())
    assert calls == []


def test_weekly_training_falls_on_the_monday_catchup(monkeypatch):
    monkeypatch.delenv("TRAIN_SCHEDULE", raising=False)
    monkeypatch.delenv("TRAIN_WEEKDAY", raising=False)
    # 9am ET Monday, in summer and winter time
    for monday_9_et in (datetime.datetime(2026, 10, 12, 13, tzinfo=datetime.timezone.utc),
                        datetime.datetime(2026, 11, 2, 14, tzinfo=datetime.timezone.utc)):
        assert schedules.should_train_tonight(monday_9_et)
        assert schedules.before_slate(monday_9_et)


def test_slate_hours_follow_eastern_time():
    utc = datetime.timezone.utc
    assert not schedules.in_slate_hours(datetime.datetime(2026, 10, 12, 15, 59, tzinfo=utc))   # 11:59 EDT
    assert schedules.in_slate_hours(datetime.datetime(2026, 10, 12, 16, tzinfo=utc))           # noon EDT
    assert schedules.in_slate_hours(datetime.datetime(2026, 10, 13, 5, tzinfo=utc))            # 1am EDT, late West Coast game
    assert not schedules.in_slate_hours(datetime.datetime(2026, 10, 13, 9, tzinfo=utc))        # 5am EDT
    assert not schedules.in_slate_hours(datetime.datetime(2026, 11, 12, 16, tzinfo=utc))       # 11am EST
    assert schedules.in_slate_hours(datetime.datetime(2026, 11, 12, 17, tzinfo=utc))           # noon EST


def test_overdue_counts_from_the_last_completion_or_process_start(monkeypatch):
    start = datetime.datetime(2026, 10, 12, 8, tzinfo=datetime.timezone.utc)
    monkeypatch.setattr(schedules, "_process_started_at", start)
    monkeypatch.setattr(schedules, "_last_completed", {})
    assert not schedules.is_overdue("nightly", start + datetime.timedelta(hours=25))
    assert schedules.is_overdue("nightly", start + datetime.timedelta(hours=27))
    schedules.mark_completed("nightly", start + datetime.timedelta(hours=24))
    assert not schedules.is_overdue("nightly", start + datetime.timedelta(hours=27))
    assert schedules.is_overdue("catch-up", start + datetime.timedelta(hours=27))


def test_overdue_check_runs_one_pipeline(monkeypatch):
    runs = []
    async def nightly():
        runs.append("nightly")
    async def catchup():
        runs.append("catch-up")
    monkeypatch.setattr(schedules, "nightly_pipeline", nightly)
    monkeypatch.setattr(schedules, "catchup_pipeline", catchup)
    monkeypatch.setattr(schedules, "is_overdue", lambda name: True)
    asyncio.run(schedules.run_overdue_pipelines())
    assert runs == ["nightly"]
    monkeypatch.setattr(schedules, "is_overdue", lambda name: name == "catch-up")
    asyncio.run(schedules.run_overdue_pipelines())
    assert runs == ["nightly", "catch-up"]


def test_run_when_free_waits_for_the_lock_instead_of_skipping():
    from app import refresh
    runs = []
    async def pipeline():
        runs.append("daily")
    async def go():
        await refresh._lock.acquire()
        refresh._status["running"] = {"name": "training"}
        waiter = asyncio.create_task(refresh.run_when_free("daily", pipeline, poll_seconds=0.01))
        await asyncio.sleep(0.05)
        assert runs == []
        refresh._status["running"] = None
        refresh._lock.release()
        assert await waiter
        # never free: gives up after max_wait
        async with refresh._lock:
            assert not await refresh.run_when_free("daily", pipeline, max_wait=datetime.timedelta(seconds=0.03),
                                                   poll_seconds=0.01)
    asyncio.run(go())
    assert runs == ["daily"]


def test_game_lines_every_15_minutes_on_the_slate_else_hourly(monkeypatch):
    fetches = []
    async def fetch():
        fetches.append(1)
    active = {"on": False}
    async def slate(now):
        return active["on"]
    monkeypatch.setattr(schedules, "fetch_current_game_lines", fetch)
    monkeypatch.setattr(schedules, "slate_active", slate)
    monkeypatch.setattr(schedules, "_game_lines_fetched_at", None)
    t = datetime.datetime(2026, 10, 12, 8, tzinfo=datetime.timezone.utc)
    async def go():
        for minutes in range(0, 120, 15):                 # off the slate: the first poll, then hourly
            await schedules.fetch_game_lines_on_schedule(t + datetime.timedelta(minutes=minutes))
        assert len(fetches) == 2
        active["on"] = True
        for minutes in range(120, 180, 15):               # on the slate: every poll
            await schedules.fetch_game_lines_on_schedule(t + datetime.timedelta(minutes=minutes))
        assert len(fetches) == 6
    asyncio.run(go())


def test_close_snapshot_once_per_game(monkeypatch):
    now = datetime.datetime(2026, 10, 12, 22, 52, tzinfo=datetime.timezone.utc)
    games = [_game(1, now + datetime.timedelta(minutes=8)), _game(2, now + datetime.timedelta(minutes=38))]
    snaps = []
    async def todays(now):
        return games
    async def pipeline(game_ids):
        snaps.append(list(game_ids))
    monkeypatch.setattr(schedules, "todays_games", todays)
    monkeypatch.setattr(schedules, "close_snapshot_pipeline", pipeline)
    monkeypatch.setattr(schedules, "_close_snapshot_taken", set())
    async def go():
        await schedules.snapshot_games_about_to_start(now)
        await schedules.snapshot_games_about_to_start(now + datetime.timedelta(minutes=3))
        await schedules.snapshot_games_about_to_start(now + datetime.timedelta(minutes=30))
    asyncio.run(go())
    assert snaps == [[1], [2]]


def _game(id, start, state="FUT"):
    from types import SimpleNamespace
    return SimpleNamespace(id=id, start_time=start, game_state=state)


def test_due_for_pregame_log_window():
    now = datetime.datetime(2026, 10, 8, 22, 40, tzinfo=datetime.timezone.utc)
    games = [_game(1, now + datetime.timedelta(minutes=20)),                  # due
             _game(2, now + datetime.timedelta(minutes=30)),                  # due, right at the lead
             _game(3, now + datetime.timedelta(minutes=50)),                  # next poll's
             _game(4, now - datetime.timedelta(minutes=5)),                   # started by the clock
             _game(5, now + datetime.timedelta(minutes=10), "LIVE"),          # started by its state
             _game(6, now + datetime.timedelta(minutes=10), "PPD"),           # postponed
             _game(7, None)]
    assert schedules.due_for_pregame_log(games, now, schedules.PREGAME_LOG_LEAD) == [1, 2]
    assert schedules.due_for_pregame_log(games, now, schedules.STARTUP_LOG_LEAD) == [1, 2, 3]


def test_pregame_log_runs_each_game_once_and_retries_a_busy_lock(monkeypatch):
    from app import refresh
    runs = []
    due = [10, 11]
    async def games_due(lead):
        return list(due)
    async def pipeline(game_ids):
        runs.append(list(game_ids))
        return True
    monkeypatch.setattr(schedules, "games_due_for_pregame_log", games_due)
    monkeypatch.setattr(schedules, "pregame_log_pipeline", pipeline)
    monkeypatch.setattr(schedules, "_pregame_log_attempted", set())

    async def busy_then_free():
        async with refresh._lock:
            refresh._status["running"] = {"name": "manual"}
            await schedules.log_games_about_to_start()   # lock held: skipped, not marked
        refresh._status["running"] = None
        await schedules.log_games_about_to_start()
        due.append(12)                                  # a later game becomes due; 10 and 11 still unlogged
        await schedules.log_games_about_to_start()
    asyncio.run(busy_then_free())
    assert runs == [[10, 11], [12]]


def test_pregame_log_retries_a_failed_log_a_few_times(monkeypatch):
    runs = []
    async def games_due(lead):
        return [10]
    async def pipeline(game_ids):
        runs.append(list(game_ids))
        return False
    monkeypatch.setattr(schedules, "games_due_for_pregame_log", games_due)
    monkeypatch.setattr(schedules, "pregame_log_pipeline", pipeline)
    monkeypatch.setattr(schedules, "_pregame_log_attempted", set())
    monkeypatch.setattr(schedules, "_pregame_log_failures", {})
    async def polls():
        for _ in range(schedules.PREGAME_LOG_MAX_TRIES + 2):
            await schedules.log_games_about_to_start()
    asyncio.run(polls())
    assert runs == [[10]] * schedules.PREGAME_LOG_MAX_TRIES


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
    async def pregame(game_ids):
        calls.append("pregame")
    async def games_due(lead):
        return [1] if missed_log else []
    monkeypatch.setattr(main, "pregame_log_pipeline", pregame)
    monkeypatch.setattr(main, "models_missing", lambda: missing)
    monkeypatch.setattr(main, "games_due_for_pregame_log", games_due)
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
