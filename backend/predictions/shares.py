"""Precomputed deployment shares (skater_game_shares).

A skater's share features (PP share, ice-time rank, shot and xG share) need every skater of each of his past games,
so predicting one skater used to load ~40 rows per game of his career. The per-game values only change when a
game's logs do, so the nightly pipeline stores them right after the log scrape and live prediction reads the
player's own rows (predict._skater_shares), computing any game not stored yet the old way. The values are
`features.skater_shares` of the same log rows, so stored and computed shares are identical; the pre-game summaries
(last 5, EWM, season, career) are still built at serve time from them, as in training.

CLI (inside the backend container):
    python -m predictions.shares refresh [--all]
"""
import argparse
import asyncio
import datetime
import json

import numpy as np
import pandas as pd
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SkaterGameLog, SkaterGameShare
from . import features as F
from .data import load_game_mates

# games per batch: bounds memory and transaction size when the whole history is (re)built
REFRESH_CHUNK_GAMES = 1000


async def stale_share_games(db: AsyncSession, seasons: list[int] | None = None) -> list[int]:
    """Games whose stored shares may differ from their logs: every game of `seasons` (default: the latest season
    in skater_game_logs, which the nightly scrape rewrites) plus any game with a log row that has no share row
    (new games, players added to a game later, an empty table)."""
    if seasons is None:
        latest = (await db.execute(select(func.max(SkaterGameLog.season)))).scalar()
        seasons = [] if latest is None else [latest]
    missing = (select(SkaterGameLog.game_id)
               .outerjoin(SkaterGameShare, (SkaterGameShare.game_id == SkaterGameLog.game_id)
                          & (SkaterGameShare.player_id == SkaterGameLog.player_id))
               .where(SkaterGameShare.player_id.is_(None)))
    recent = select(SkaterGameLog.game_id).where(SkaterGameLog.season.in_(seasons))
    stmt = missing.union(recent)
    return sorted(int(g) for g in (await db.execute(stmt)).scalars().all())


def share_rows(mates: pd.DataFrame, computed_at: datetime.datetime) -> list[dict]:
    """skater_game_shares rows for `load_game_mates` output (NaN shares, e.g. a team without PP time, become NULL)."""
    shares = F.skater_shares(mates)
    out = shares[["game_id", "player_id"]].astype(int).astype(object)
    for c in F.SKATER_SHARE_STATS:
        values = shares[c].astype(float)
        out[c] = values.astype(object).where(np.isfinite(values), None)
    out["computed_at"] = computed_at
    return out.to_dict("records")


async def refresh_skater_shares(db: AsyncSession, seasons: list[int] | None = None, rebuild: bool = False,
                                now: datetime.datetime | None = None) -> dict:
    """Recomputes stored shares for `stale_share_games` (every logged game with `rebuild`), whole games at a time:
    a game's rows are deleted and rewritten from all of its skater logs, so team totals stay consistent."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if rebuild:
        game_ids = sorted(int(g) for g in (await db.execute(select(SkaterGameLog.game_id).distinct())).scalars().all())
    else:
        game_ids = await stale_share_games(db, seasons)
    written = 0
    for i in range(0, len(game_ids), REFRESH_CHUNK_GAMES):
        chunk = game_ids[i:i + REFRESH_CHUNK_GAMES]
        rows = share_rows(await load_game_mates(db, chunk), now)
        await db.execute(delete(SkaterGameShare).where(SkaterGameShare.game_id.in_(chunk)))
        if rows:
            await db.execute(insert(SkaterGameShare), rows)
        await db.commit()   # per chunk, so a failure late in a full rebuild keeps the chunks already written
        written += len(rows)
    return {"games": len(game_ids), "rows": written}


async def _cli(args) -> None:
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        out = await refresh_skater_shares(db, rebuild=args.all)
    print(json.dumps(out))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Precomputed skater deployment shares")
    sub = parser.add_subparsers(dest="cmd", required=True)
    refresh = sub.add_parser("refresh")
    refresh.add_argument("--all", action="store_true", help="rebuild every logged game, not just stale ones")
    asyncio.run(_cli(parser.parse_args(argv)))


if __name__ == "__main__":
    main()
