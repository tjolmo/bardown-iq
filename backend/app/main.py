from app.schedules import train_models
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from .database import engine
from .routers import teams_router, player_router, admin_router
from . import refresh
from .database import AsyncSessionLocal
from .schedules import (add_current_teams_to_db, add_old_teams_to_db, fetch_current_rosters_for_all_teams, 
                        fetch_current_schedules_for_all_teams, fetch_all_season_schedules_for_all_teams, scrape_all_player_logs,
                        fetch_current_scores, fetch_current_player_props, nightly_pipeline)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

async def run_startup_refresh():
    """Initial data refresh, run in the background so the API can serve requests while it works.
    Steps are ordered by dependency; a failing step is logged and does not stop the rest."""
    steps = [
        ("teams", add_current_teams_to_db),
        ("old teams", add_old_teams_to_db),
        ("schedules", fetch_current_schedules_for_all_teams),
        ("rosters", fetch_current_rosters_for_all_teams),
        ("player logs", scrape_all_player_logs),
        ("training", train_models),
    ]
    for name, step in steps:
        try:
            await step()
        except Exception as e:
            print(f"Startup step '{name}' failed: {e!r}")
    print("Startup refresh finished")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = AsyncIOScheduler()
    # one ordered nightly job instead of independent 03:00/04:00 jobs that raced each other
    # run through the shared lock so the nightly run never overlaps a startup or manual refresh
    scheduler.add_job(refresh.run_exclusive, args=["nightly", nightly_pipeline], trigger="cron", hour=3, max_instances=1, coalesce=True, misfire_grace_time=3600)
    scheduler.add_job(fetch_current_scores, trigger="interval", minutes=10)
    scheduler.start()
    refresh.start_in_background("startup", run_startup_refresh)

    yield

    print("Closing Scheduler and Postgres connection")
    refresh.cancel_background()
    scheduler.shutdown(wait=False)
    await engine.dispose()

app = FastAPI(lifespan=lifespan)
app.include_router(teams_router.router)
app.include_router(player_router.router)
app.include_router(admin_router.router)

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