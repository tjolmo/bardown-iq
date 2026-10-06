from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import TeamGameStats
import datetime

async def upsert_team_game_stats(db: AsyncSession, rows: list[dict]):
    """Upserts MoneyPuck team game stats in batches (a full backfill is ~45k rows)."""
    for i in range(0, len(rows), 1000):
        stmt = insert(TeamGameStats).values(rows[i : i + 1000])
        stmt = stmt.on_conflict_do_update(
            index_elements=["game_id", "team_tri_code"],
            set_={**{c: stmt.excluded[c] for c in rows[0] if c not in ("game_id", "team_tri_code")},
                  "last_updated": datetime.datetime.now(datetime.timezone.utc)},
        )
        await db.execute(stmt)
    await db.commit()
