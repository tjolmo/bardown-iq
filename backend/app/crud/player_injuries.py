import datetime

import pandas as pd
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PlayerInjury

INJURY_COLUMNS = ["espn_athlete_id", "player_id", "team", "full_name", "position", "status", "espn_status",
                  "fantasy_status", "injury_type", "roster_status", "report_date", "return_date", "espn_injury_id",
                  "comment"]
# an injury report older than this is ignored (ESPN down for a day): expected lineups fall back to the previous game's
MAX_REPORT_AGE = datetime.timedelta(hours=36)


async def insert_injury_snapshot(db: AsyncSession, rows: list[dict], fetched_at: datetime.datetime | None = None) -> int:
    """Appends one fetch of the injury report (every listed player once, same fetched_at). Returns rows written."""
    fetched_at = fetched_at or datetime.datetime.now(datetime.timezone.utc)
    by_athlete = {}
    for r in rows:
        by_athlete.setdefault(r["espn_athlete_id"], {c: r.get(c) for c in INJURY_COLUMNS})
    if not by_athlete:
        return 0
    values = [{**r, "fetched_at": fetched_at} for r in by_athlete.values()]
    await db.execute(insert(PlayerInjury), values)
    await db.commit()
    return len(values)


async def get_recently_listed_out(db: AsyncSession, player_ids: list[int], statuses: set[str],
                                  since: datetime.datetime) -> set[int]:
    """Players among `player_ids` that an injury snapshot fetched since `since` listed with one of `statuses`."""
    if not player_ids:
        return set()
    stmt = select(PlayerInjury.player_id).where(PlayerInjury.player_id.in_(player_ids),
                                                PlayerInjury.status.in_(statuses),
                                                PlayerInjury.fetched_at >= since).distinct()
    return set((await db.execute(stmt)).scalars().all())


async def load_injury_report(db: AsyncSession, as_of: datetime.datetime | None = None,
                             max_age: datetime.timedelta = MAX_REPORT_AGE) -> pd.DataFrame | None:
    """The latest injury snapshot fetched at or before `as_of` (default now), as a DataFrame with fetched_at plus
    INJURY_COLUMNS; None when there is none fetched within `max_age` of `as_of`."""
    as_of = as_of or datetime.datetime.now(datetime.timezone.utc)
    latest = (await db.execute(select(func.max(PlayerInjury.fetched_at))
                               .where(PlayerInjury.fetched_at <= as_of, PlayerInjury.fetched_at > as_of - max_age))).scalar()
    if latest is None:
        return None
    stmt = select(PlayerInjury.fetched_at, *[getattr(PlayerInjury, c) for c in INJURY_COLUMNS]).where(
        PlayerInjury.fetched_at == latest)
    rows = (await db.execute(stmt)).mappings().all()
    return pd.DataFrame([dict(r) for r in rows], columns=["fetched_at"] + INJURY_COLUMNS)
