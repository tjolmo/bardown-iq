"""Timing of the afternoon prediction log and single skater predictions (RESULTS_v5.md section 6).

Runs `log_predictions` for one slate with writes rolled back (commits become flushes), timing where each skater
prediction spends its time, then times `predict_skater` alone for a few players with the team context warm.

    python -m predictions.experiments.shares_benchmark --date 20261008 [--profile out.prof] [--no-table]

--no-table hides the precomputed shares table, so the fallback (every teammate's row of every past game, the v4 path)
is timed.
"""
import argparse
import asyncio
import cProfile
import inspect
import datetime
import json
import pstats
import statistics
import time
from collections import defaultdict
from functools import wraps

from predictions import data as D, features as F, predict as P, prediction_log as L

timings: dict[str, list[float]] = defaultdict(list)


def _timed(module, name, label=None):
    """Wraps module.name (sync or async) so each call's wall time lands in timings[label]."""
    fn = getattr(module, name)
    label = label or name
    if inspect.iscoroutinefunction(fn):
        @wraps(fn)
        async def wrapper(*a, **k):
            t = time.perf_counter()
            try:
                return await fn(*a, **k)
            finally:
                timings[label].append(time.perf_counter() - t)
    else:
        @wraps(fn)
        def wrapper(*a, **k):
            t = time.perf_counter()
            try:
                return fn(*a, **k)
            finally:
                timings[label].append(time.perf_counter() - t)
    setattr(module, name, wrapper)


def _instrument():
    _timed(P, "predict_skater")
    _timed(P, "predict_goalie")
    _timed(P, "_team_context")
    _timed(P, "load_skater_logs")
    _timed(P, "load_game_mates")
    _timed(P, "_load_shares")
    _timed(P, "_skater_shares")
    _timed(F, "skater_shares")
    _timed(F, "skater_features")


def _summary(wall: float) -> dict:
    out = {"wall_s": round(wall, 2)}
    for k, v in sorted(timings.items()):
        out[k] = {"calls": len(v), "total_s": round(sum(v), 2), "median_ms": round(1000 * statistics.median(v), 1),
                  "max_ms": round(1000 * max(v), 1)}
    return out


async def _run(args) -> dict:
    from app.database import AsyncSessionLocal
    if args.no_table:
        async def _no_table(db, player_id, game_ids):
            return None
        P._load_shares = _no_table
    _instrument()
    report = {}
    now = datetime.datetime.strptime(str(args.date), "%Y%m%d").replace(hour=12, tzinfo=datetime.timezone.utc)
    async with AsyncSessionLocal() as db:
        # dry run: every write stays in one transaction that is rolled back at the end
        db.commit = db.flush
        prof = cProfile.Profile() if args.profile else None
        t = time.perf_counter()
        if prof:
            prof.enable()
        summary = await L.log_predictions(db, game_date=args.date, now=now, run_id="shares-benchmark")
        if prof:
            prof.disable()
            prof.dump_stats(args.profile)
        report["log"] = {"summary": summary, **_summary(time.perf_counter() - t)}
        await db.rollback()

        # single predictions (API path) with the team context already built
        timings.clear()
        games = await D.load_games(db)
        game = games[games["date"] == args.date].iloc[0]
        game = type("G", (), {"id": int(game["id"]), "date": int(game["date"]), "season": int(game["season"]) * 10000 + int(game["season"]) + 1,
                              "home_team_tri_code": game["home_team_tri_code"], "away_team_tri_code": game["away_team_tri_code"]})
        rosters = await L._roster(db, [game.home_team_tri_code, game.away_team_tri_code])
        skaters = [(pid, team) for pid, team, pos in rosters if pos != "G"]
        single = []
        for pid, team in skaters[:args.singles]:
            t = time.perf_counter()
            await P.predict_skater(db, pid, team, game)
            single.append(time.perf_counter() - t)
        report["single"] = {"players": len(single), "median_ms": round(1000 * statistics.median(single), 1),
                            "max_ms": round(1000 * max(single), 1), **_summary(sum(single))}
    return report


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=int, required=True)
    parser.add_argument("--profile")
    parser.add_argument("--no-table", action="store_true")
    parser.add_argument("--singles", type=int, default=20)
    args = parser.parse_args(argv)
    print(json.dumps(asyncio.run(_run(args)), indent=1, default=str))
    if args.profile:
        pstats.Stats(args.profile).sort_stats("cumulative").print_stats(35)


if __name__ == "__main__":
    main()
