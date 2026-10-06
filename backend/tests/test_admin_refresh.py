import asyncio
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import httpx
from fastapi import FastAPI

from app import refresh
from app.routers import admin_router

TOKEN = "test-token"


def make_app():
    app = FastAPI()
    app.include_router(admin_router.router)
    return app


def run(go):
    async def wrapper():
        transport = httpx.ASGITransport(app=make_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await go(client)
    return asyncio.run(wrapper())


def test_disabled_without_admin_token(monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    res = run(lambda c: c.post("/admin/refresh", headers={"X-Admin-Token": "anything"}))
    assert res.status_code == 503


def test_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    assert run(lambda c: c.post("/admin/refresh")).status_code == 401
    assert run(lambda c: c.post("/admin/refresh", headers={"X-Admin-Token": "wrong"})).status_code == 401
    assert run(lambda c: c.get("/admin/refresh", headers={"X-Admin-Token": "wrong"})).status_code == 401


def test_starts_refresh_and_rejects_overlap(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    headers = {"X-Admin-Token": TOKEN}
    release = None
    calls = []

    async def fake_refresh():
        calls.append(1)
        await release.wait()

    monkeypatch.setattr(admin_router, "full_refresh", fake_refresh)

    async def go(client):
        nonlocal release
        release = asyncio.Event()
        first = await client.post("/admin/refresh", headers=headers)
        await asyncio.sleep(0)  # let the background task take the lock
        second = await client.post("/admin/refresh", headers=headers)
        running = await client.get("/admin/refresh", headers=headers)
        # the nightly job is skipped, not queued, while a refresh holds the lock
        nightly_ran = await refresh.run_exclusive("nightly", fake_refresh)
        release.set()
        await refresh._task
        done = await client.get("/admin/refresh", headers=headers)
        return first, second, running, nightly_ran, done

    first, second, running, nightly_ran, done = run(go)
    assert first.status_code == 202
    assert second.status_code == 409
    assert running.json()["is_running"] is True
    assert running.json()["running"]["name"] == "full refresh"
    assert nightly_ran is False
    assert calls == [1]
    body = done.json()
    assert body["is_running"] is False
    assert body["last_run"]["name"] == "full refresh"
    assert body["last_run"]["error"] is None


def test_records_pipeline_error():
    async def boom():
        raise RuntimeError("nhl api down")

    async def go():
        assert await refresh.run_exclusive("full refresh", boom) is True
        return refresh.get_status()

    status = asyncio.run(go())
    assert status["is_running"] is False
    assert "nhl api down" in status["last_run"]["error"]
