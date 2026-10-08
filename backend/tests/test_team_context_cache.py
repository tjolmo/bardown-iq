"""The team context is served from the cache while a stale one rebuilds in the background; only a cold cache waits."""
import asyncio
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from predictions import predict as P


@pytest.fixture
def builds(monkeypatch):
    """Replaces the DB load + build with a counter: each rebuild yields a context tagged with its build number."""
    calls = []

    async def fake_rebuild(db):
        generation = P._context_generation
        calls.append(db)
        await asyncio.sleep(0.01)
        P._context = {"team_feats": len(calls), "built_at": P.time.monotonic(), "team_mtime": P._team_mtime(),
                      "generation": generation}
        return P._context

    class FakeSession:
        async def __aenter__(self):
            return "bg-session"

        async def __aexit__(self, *a):
            return False

    import app.database
    monkeypatch.setattr(P, "_rebuild_context", fake_rebuild)
    monkeypatch.setattr(app.database, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(P, "_context", {"built_at": 0.0})
    monkeypatch.setattr(P, "_context_refresh", None)
    monkeypatch.setattr(P, "_context_failed_at", 0.0)
    return calls


def test_cold_cache_builds_inline_once(builds):
    async def run():
        return await asyncio.gather(*(P._team_context("req") for _ in range(5)))
    results = asyncio.run(run())
    assert [r["team_feats"] for r in results] == [1] * 5 and builds == ["req"]


def test_stale_context_is_served_while_it_rebuilds_in_the_background(builds):
    async def run():
        await P._team_context("req")
        P._context["built_at"] -= P.CONTEXT_TTL_SECONDS + 1
        served = [(await P._team_context("req"))["team_feats"] for _ in range(3)]
        await P._context_refresh
        return served, (await P._team_context("req"))["team_feats"]
    served, after = asyncio.run(run())
    assert served == [1, 1, 1] and after == 2
    assert builds == ["req", "bg-session"]      # one background rebuild, on its own session


def test_invalidate_triggers_background_rebuild_and_refresh_rebuilds_now(builds):
    async def run():
        await P._team_context("req")
        P.invalidate_team_context()
        assert (await P._team_context("req"))["team_feats"] == 1
        await P._context_refresh
        P.invalidate_team_context()
        return (await P.refresh_team_context("job"))["team_feats"]
    assert asyncio.run(run()) == 3 and builds == ["req", "bg-session", "job"]


def test_rebuild_started_before_an_invalidation_stays_stale(builds):
    async def run():
        await P._team_context("req")
        P.invalidate_team_context()
        await P._team_context("req")    # starts the background rebuild
        await asyncio.sleep(0.005)      # ...which is now loading
        P.invalidate_team_context()     # a fetch lands while the rebuild is running
        await P._context_refresh
        return P._context_stale(), (await P.refresh_team_context("job"))["team_feats"]
    stale, refreshed = asyncio.run(run())
    assert stale and refreshed == 3


def test_failed_background_rebuild_keeps_serving_and_backs_off(builds, monkeypatch):
    async def run():
        await P._team_context("req")

        async def boom(db):
            builds.append("failed")
            raise RuntimeError("db down")
        monkeypatch.setattr(P, "_rebuild_context", boom)
        P.invalidate_team_context()
        assert (await P._team_context("req"))["team_feats"] == 1
        await P._context_refresh
        for _ in range(3):              # no retry within CONTEXT_RETRY_SECONDS
            assert (await P._team_context("req"))["team_feats"] == 1
    asyncio.run(run())
    assert builds == ["req", "failed"]
