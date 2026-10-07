import datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import GameStarter

STATUS_RANK = {"projected": 0, "probable": 1, "confirmed": 2}
STARTER_COLUMNS = ["game_id", "team", "player_id", "status", "source", "fetched_at"]


async def upsert_game_starters(db: AsyncSession, picks: list, fetched_at: datetime.datetime | None = None) -> int:
    """Stores starter picks (StarterPick or dicts), one row per (game_id, team); the latest fetch replaces the row,
    except that a confirmed starter is never replaced by a weaker status for the same game."""
    fetched_at = fetched_at or datetime.datetime.now(datetime.timezone.utc)
    rows = {}
    for p in picks:
        p = p.model_dump() if hasattr(p, "model_dump") else dict(p)
        rows[(p["game_id"], p["team"])] = {"game_id": p["game_id"], "team": p["team"], "player_id": p["player_id"],
                                           "status": p["status"], "source": p["source"], "fetched_at": fetched_at}
    if not rows:
        return 0
    stmt = insert(GameStarter).values(list(rows.values()))
    stmt = stmt.on_conflict_do_update(
        index_elements=["game_id", "team"],
        set_={c: stmt.excluded[c] for c in ("player_id", "status", "source", "fetched_at")},
        # keep a confirmed row unless the new one is confirmed too (e.g. the play-by-play after puck drop)
        where=(GameStarter.status != "confirmed") | (stmt.excluded.status == "confirmed"),
    )
    await db.execute(stmt)
    await db.commit()
    return len(rows)


async def load_game_starters(db: AsyncSession, game_ids: list[int] | None = None, min_game_id: int | None = None) -> pd.DataFrame:
    """Stored starters as a DataFrame (game_id, team, player_id, status, source, fetched_at), optionally limited to
    `game_ids` or to game ids >= `min_game_id`."""
    stmt = select(*[getattr(GameStarter, c) for c in STARTER_COLUMNS])
    if game_ids is not None:
        stmt = stmt.where(GameStarter.game_id.in_(game_ids))
    if min_game_id is not None:
        stmt = stmt.where(GameStarter.game_id >= min_game_id)
    rows = (await db.execute(stmt)).mappings().all()
    return pd.DataFrame([dict(r) for r in rows], columns=STARTER_COLUMNS)
