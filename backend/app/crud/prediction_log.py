from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PredictionLog


async def get_pregame_home_win_probs(db: AsyncSession, game_ids: list[int]) -> dict[int, float]:
    """game_id -> the home win probability the forward test logged before puck drop (its last pre-game run, when the
    afternoon log ran more than once or the model was retrained in between). Games never logged are absent."""
    if not game_ids:
        return {}
    stmt = (select(PredictionLog.game_id, PredictionLog.home_win_prob)
            .where(PredictionLog.game_id.in_(game_ids), PredictionLog.logged_at <= PredictionLog.start_time)
            .order_by(PredictionLog.game_id, PredictionLog.logged_at))
    # ordered by logged_at, so each game keeps its latest pre-game row
    return {game_id: float(p) for game_id, p in (await db.execute(stmt)).all()}
