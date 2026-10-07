import datetime

import pandas as pd
from sqlalchemy import select, and_, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import GameStarter, Games
from .games import FINISHED_GAME_STATES

STATUS_RANK = {"projected": 0, "probable": 1, "confirmed": 2, "actual": 3}
STARTER_COLUMNS = ["game_id", "team", "player_id", "status", "source", "fetched_at"]
# rows holding who actually started (NHL play-by-play / boxscore); the other sources are pre-game picks
ACTUAL_SOURCE, ACTUAL_STATUS = "nhl", "actual"


async def upsert_game_starters(db: AsyncSession, picks: list, fetched_at: datetime.datetime | None = None) -> int:
    """Stores starter picks (StarterPick or dicts), one row per (game_id, team, source); the latest fetch replaces
    the row, except that a confirmed starter is never replaced by a weaker status from the same source. Actual
    starters (source "nhl") live beside the ESPN pre-game pick instead of overwriting it."""
    fetched_at = fetched_at or datetime.datetime.now(datetime.timezone.utc)
    rows = {}
    for p in picks:
        p = p.model_dump() if hasattr(p, "model_dump") else dict(p)
        rows[(p["game_id"], p["team"], p["source"])] = {
            "game_id": p["game_id"], "team": p["team"], "player_id": p["player_id"],
            "status": p["status"], "source": p["source"], "fetched_at": fetched_at}
    if not rows:
        return 0
    values = list(rows.values())
    # Postgres caps a statement at 65535 bind parameters (6 per row)
    for start in range(0, len(values), 5000):
        stmt = insert(GameStarter).values(values[start:start + 5000])
        stmt = stmt.on_conflict_do_update(
            index_elements=["game_id", "team", "source"],
            set_={c: stmt.excluded[c] for c in ("player_id", "status", "fetched_at")},
            # keep a confirmed row unless the new one is confirmed (or actual) too
            where=(GameStarter.status != "confirmed") | stmt.excluded.status.in_(("confirmed", ACTUAL_STATUS)),
        )
        await db.execute(stmt)
    await db.commit()
    return len(rows)


async def load_game_starters(db: AsyncSession, game_ids: list[int] | None = None, min_game_id: int | None = None) -> pd.DataFrame:
    """Stored starters as a DataFrame (game_id, team, player_id, status, source, fetched_at), optionally limited to
    `game_ids` or to game ids >= `min_game_id`. Pre-game picks and actual starters (status "actual") both appear."""
    stmt = select(*[getattr(GameStarter, c) for c in STARTER_COLUMNS])
    if game_ids is not None:
        stmt = stmt.where(GameStarter.game_id.in_(game_ids))
    if min_game_id is not None:
        stmt = stmt.where(GameStarter.game_id >= min_game_id)
    rows = (await db.execute(stmt)).mappings().all()
    return pd.DataFrame([dict(r) for r in rows], columns=STARTER_COLUMNS)


async def get_games_missing_actual_starters(db: AsyncSession, min_season: int | None = None, max_season: int | None = None,
                                            limit: int | None = None) -> list[int]:
    """Finished regular-season and playoff games (oldest first) without an actual starter stored for both teams.
    Seasons are start years (2008 for 2008-09)."""
    have = (select(GameStarter.game_id).where(GameStarter.source == ACTUAL_SOURCE)
            .group_by(GameStarter.game_id).having(func.count() >= 2))
    game_type = Games.id // 10000 % 100
    conds = [Games.game_state.in_(FINISHED_GAME_STATES), game_type.in_((2, 3)), Games.id.not_in(have)]
    if min_season is not None:
        conds.append(Games.season >= min_season * 10000)
    if max_season is not None:
        conds.append(Games.season < (max_season + 1) * 10000)
    stmt = select(Games.id).where(and_(*conds)).order_by(Games.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list((await db.execute(stmt)).scalars().all())


def actual_starter_rows(game_id: int, starters: dict[str, int]) -> list[dict]:
    """game_starters rows for the actual starters of one game (team -> goalie)."""
    return [{"game_id": game_id, "team": team, "player_id": pid, "status": ACTUAL_STATUS, "source": ACTUAL_SOURCE}
            for team, pid in starters.items()]
