import asyncio
import datetime
import os
from app.schedules import train_models, models_missing, train_schedule
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from .database import engine
from .routers import teams_router, player_router, admin_router, edges_router
from . import refresh
from .database import AsyncSessionLocal
from .schedules import (add_current_teams_to_db, add_old_teams_to_db, fetch_current_rosters_for_all_teams, 
                        fetch_current_schedules_for_all_teams, scrape_all_player_logs, scrape_team_stats,
                        fetch_current_scores, fetch_game_lines_on_schedule, nightly_pipeline, catchup_pipeline,
                        daytime_odds_pipeline, refresh_game_day_news, run_overdue_pipelines,
                        fetch_game_day_lineups, log_games_about_to_start, snapshot_games_about_to_start,
                        games_due_for_pregame_log, pregame_log_pipeline, STARTUP_LOG_LEAD, PREGAME_LOG_POLL_MINUTES)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from external.nhl.games import live_poll_minutes

PACIFIC = "America/Los_Angeles"
EASTERN = "America/New_York"
# how late a daily cron run may still start (e.g. after the machine wakes up); later than that the overdue check runs it
DAILY_GRACE = 6 * 3600
DAYTIME_GRACE = 2 * 3600

def scheduler_enabled() -> bool:
    """SCHEDULER_ENABLED=0 turns off every scheduled job and the startup refresh (a dev container sharing the
    forward-test container's database, which does the fetching and logging)."""
    return os.environ.get("SCHEDULER_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")

async def run_startup_refresh():
    """Initial data refresh, run in the background so the API can serve requests while it works.
    Steps are ordered by dependency; a failing step is logged and does not stop the rest.
    Training only runs when a bundle is missing (TRAIN_ON_STARTUP=always forces it): a restart, or a --reload after
    a code edit, must not refit the models and start a new model_version mid forward test."""
    steps = []
    if not models_missing():
        # first, before they start: the games the pre-game log polls would miss while this refresh holds the lock
        try:
            due = await games_due_for_pregame_log(STARTUP_LOG_LEAD)
        except Exception as e:
            print(f"Startup: pre-game log check failed: {e!r}")
            due = []
        if due:
            steps.append(("pregame log (catch-up)", lambda: pregame_log_pipeline(due)))
    steps += [
        ("teams", add_current_teams_to_db),
        ("old teams", add_old_teams_to_db),
        ("schedules", fetch_current_schedules_for_all_teams),
        ("rosters", fetch_current_rosters_for_all_teams),
        ("player logs", scrape_all_player_logs),
        ("team stats", scrape_team_stats),
    ]
    if models_missing() or os.environ.get("TRAIN_ON_STARTUP", "").strip().lower() == "always":
        steps.append(("training", train_models))
    for name, step in steps:
        try:
            await step()
        except Exception as e:
            print(f"Startup step '{name}' failed: {e!r}")
    print("Startup refresh finished")

async def warm_caches():
    """Builds the team context, then the edge board, so the first page views after a start (or a --reload) don't
    wait ~8 s and ~45 s on them. Runs on every stack, scheduler or not."""
    from predictions.predict import warm_team_context
    from .edge_board import warm_board
    await warm_team_context()
    try:
        await warm_board(AsyncSessionLocal)
    except Exception as e:
        print(f"Edge board warm-up failed (built on first use instead): {e!r}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = AsyncIOScheduler()
    print(f"Code commit {os.environ.get('GIT_COMMIT', 'unknown')}, TRAIN_SCHEDULE={train_schedule()}")
    warm = asyncio.create_task(warm_caches())
    if not scheduler_enabled():
        print("SCHEDULER_ENABLED=0: no scheduled jobs and no startup refresh")
        yield
        warm.cancel()
        await engine.dispose()
        return
    # every cron job names its timezone: the container runs on UTC, and ET/PT times must follow the clock changes.
    # The daily pipelines go through the shared lock and wait for it (run_when_free) instead of being dropped when a
    # startup, manual refresh or training run holds it; a run missed by more than its grace (the machine slept)
    # is picked up by the overdue check.
    # midnight Pacific, after the last West Coast game has ended (07:00 UTC in summer time, 08:00 in winter)
    scheduler.add_job(refresh.run_when_free, args=["nightly", nightly_pipeline], trigger="cron", hour=0,
                      timezone=PACIFIC, max_instances=1, coalesce=True, misfire_grace_time=DAILY_GRACE)
    # 9am ET: last night's late games again (MoneyPuck, starters, lineups, scoring), the day's schedule changes and
    # call-ups, and the weekly training on the complete logs
    scheduler.add_job(refresh.run_when_free, args=["catch-up", catchup_pipeline], trigger="cron", hour=9,
                      timezone=EASTERN, max_instances=1, coalesce=True, misfire_grace_time=DAILY_GRACE)
    # 11:00, 13:30 and 16:30 ET: call-ups, starting goalies, injuries, ESPN prices and PropLine props, edge board
    for name, hour, minute in (("morning odds", 11, 0), ("midday odds", 13, 30), ("afternoon odds", 16, 30)):
        scheduler.add_job(refresh.run_when_free, args=[name, daytime_odds_pipeline],
                          kwargs={"max_wait": datetime.timedelta(hours=1)}, trigger="cron", hour=hour, minute=minute,
                          timezone=EASTERN, max_instances=1, coalesce=True, misfire_grace_time=DAYTIME_GRACE)
    # on the hour and half hour while the slate is active: starting goalies (and hourly the injury report)
    scheduler.add_job(refresh_game_day_news, trigger="cron", minute="0,30", timezone="UTC", max_instances=1, coalesce=True)
    # the nightly run or the catch-up, if one hasn't completed in 26 hours
    scheduler.add_job(run_overdue_pipelines, trigger="cron", minute="*/15", timezone="UTC", max_instances=1, coalesce=True)
    # LIVE_SCORES_POLL_MINUTES (default 10); the job only calls the NHL API while a game is about to start or under way
    scheduler.add_job(fetch_current_scores, trigger="interval", minutes=live_poll_minutes(), max_instances=1, coalesce=True)
    # lineups and scratches as the NHL posts them before puck drop, and the lines used once a game ends; also only
    # calls the NHL API around games
    scheduler.add_job(fetch_game_day_lineups, trigger="interval", minutes=live_poll_minutes(), max_instances=1, coalesce=True)
    # the site's live moneylines: one bulk PropLine request every 15 minutes during the slate, hourly otherwise
    # (about 55 of the free tier's 1,000 a day; first run at startup)
    scheduler.add_job(fetch_game_lines_on_schedule, trigger="cron", minute="*/15", timezone="UTC", max_instances=1,
                      coalesce=True, next_run_time=datetime.datetime.now(datetime.timezone.utc))
    # the forward test's prediction log, ~30 minutes before each game: starters, injuries and prices for the games
    # about to start, then the log; no API call when no game is due
    scheduler.add_job(log_games_about_to_start, trigger="interval", minutes=PREGAME_LOG_POLL_MINUTES, max_instances=1, coalesce=True)
    # the closing snapshot, 5-10 minutes before each game: PropLine's last pregame quotes and ESPN's game prices
    # (offset half a poll from the pre-game log so the two don't land on the lock at the same moment)
    scheduler.add_job(snapshot_games_about_to_start, trigger="interval", minutes=PREGAME_LOG_POLL_MINUTES, max_instances=1,
                      coalesce=True, next_run_time=datetime.datetime.now(datetime.timezone.utc)
                      + datetime.timedelta(minutes=PREGAME_LOG_POLL_MINUTES / 2))
    scheduler.start()
    refresh.start_in_background("startup", run_startup_refresh)

    yield

    print("Closing Scheduler and Postgres connection")
    warm.cancel()
    refresh.cancel_background()
    scheduler.shutdown(wait=False)
    await engine.dispose()

app = FastAPI(lifespan=lifespan)
app.include_router(teams_router.router)
app.include_router(player_router.router)
app.include_router(admin_router.router)
app.include_router(edges_router.router)

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
),