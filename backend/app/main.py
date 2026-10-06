from app.schedules import train_models
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from .database import engine
from .routers import teams_router, player_router
from .database import AsyncSessionLocal
from .schedules import (add_current_teams_to_db, add_old_teams_to_db, fetch_current_rosters_for_all_teams, 
                        fetch_current_schedules_for_all_teams, fetch_all_season_schedules_for_all_teams, update_daily_features, scrape_all_player_logs,
                        fetch_current_scores, fetch_current_player_props)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Connecting to Postgres")
    async with AsyncSessionLocal() as db:
        print("Connected to Postgres")
        await add_current_teams_to_db()
        await add_old_teams_to_db()
        await fetch_current_schedules_for_all_teams()
        await fetch_current_rosters_for_all_teams()
        await scrape_all_player_logs()
        await update_daily_features()
        await train_models()

        scheduler = AsyncIOScheduler()
        scheduler.add_job(fetch_current_schedules_for_all_teams,trigger="cron",hour=3)
        scheduler.add_job(fetch_current_rosters_for_all_teams,trigger="cron",hour=3)
        scheduler.add_job(scrape_all_player_logs, trigger="cron",hour=3)
        scheduler.add_job(fetch_current_scores, trigger="interval", minutes=10)
        scheduler.add_job(fetch_current_player_props, trigger="cron", hour=3)
        scheduler.add_job(update_daily_features, trigger="cron", hour=3)
        scheduler.add_job(train_models, trigger="cron", hour=4)
        scheduler.start() 
        

    yield 
    
    print("Closing Scheduler and Postgres connection")
    await engine.dispose()

app = FastAPI(lifespan=lifespan)
app.include_router(teams_router.router)
app.include_router(player_router.router)

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
),