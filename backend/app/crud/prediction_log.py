from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Games, PlayerPredictionLog, PredictionLog


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


async def get_pregame_player_expectations(db: AsyncSession, player_id: int, game_ids: list[int]) -> dict[int, dict[str, float]]:
    """game_id -> {model stat: expected count} the forward test logged for the player before puck drop (its last
    pre-game run per stat). Games never logged for the player are absent."""
    if not game_ids:
        return {}
    stmt = (select(PlayerPredictionLog.game_id, PlayerPredictionLog.stat, PlayerPredictionLog.expected)
            .join(Games, Games.id == PlayerPredictionLog.game_id)
            .where(PlayerPredictionLog.player_id == player_id, PlayerPredictionLog.game_id.in_(game_ids),
                   PlayerPredictionLog.logged_at <= Games.start_time)
            .order_by(PlayerPredictionLog.game_id, PlayerPredictionLog.logged_at))
    out: dict[int, dict[str, float]] = {}
    # ordered by logged_at, so each stat keeps its latest pre-game row
    for game_id, stat, expected in (await db.execute(stmt)).all():
        out.setdefault(game_id, {})[stat] = float(expected)
    return out
