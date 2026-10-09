from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import GameOdds, Games
import datetime

GAME_ODDS_COLUMNS = [
    "game_id", "date", "home_team_tri_code", "away_team_tri_code", "home_moneyline", "away_moneyline",
    "home_prob_novig", "open_home_prob_novig", "open_home_moneyline", "open_away_moneyline",
    "total_line", "open_total_line", "n_books", "books", "espn_event_id",
]

def game_odds_upsert_stmt(batch: list[dict]):
    """INSERT ... ON CONFLICT (game_id) DO UPDATE for a batch of game_odds rows."""
    now = datetime.datetime.now(datetime.timezone.utc)
    stmt = insert(GameOdds).values([{**{c: row.get(c) for c in GAME_ODDS_COLUMNS}, "last_updated": now} for row in batch])
    return stmt.on_conflict_do_update(
        index_elements=["game_id"],
        set_={**{c: stmt.excluded[c] for c in GAME_ODDS_COLUMNS if c != "game_id"}, "last_updated": now},
    )

async def upsert_game_odds(db: AsyncSession, rows: list[dict]):
    """Upserts per-game closing odds consensus rows (see external.espn.game_odds.build_game_odds_rows)."""
    if not rows:
        return
    for i in range(0, len(rows), 1000):
        await db.execute(game_odds_upsert_stmt(rows[i : i + 1000]))
    await db.commit()

async def get_game_odds(db: AsyncSession, game_ids: list[int] | None = None) -> list[GameOdds]:
    """All stored game odds, or only those for the given NHL game ids."""
    query = select(GameOdds).order_by(GameOdds.date, GameOdds.game_id)
    if game_ids is not None:
        query = query.where(GameOdds.game_id.in_(game_ids))
    result = await db.execute(query)
    return list(result.scalars().all())

async def get_games_for_odds_matching(db: AsyncSession, start_date: int, end_date: int) -> list[dict]:
    """Games between two YYYYMMDD dates as the dicts external.espn.odds.match_nhl_ids expects."""
    result = await db.execute(
        select(Games.id, Games.date, Games.home_team_tri_code, Games.away_team_tri_code)
        .where(Games.date >= start_date, Games.date <= end_date)
    )
    return [dict(row._mapping) for row in result.all()]
