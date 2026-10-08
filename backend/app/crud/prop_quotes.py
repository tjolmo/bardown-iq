import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PropQuote

QUOTE_KEY = ["game_id", "player_id", "prop_type", "over_under", "line", "bookmaker"]
BATCH = 2000    # well under asyncpg's 32767 bind-parameter limit (13 columns per row)
PROVIDER = "propline"


def build_quote_rows(quotes: list[dict], fetched_at: datetime.datetime, provider: str = PROVIDER) -> list[dict]:
    """One row per primary key (ON CONFLICT cannot touch a row twice in one statement); the last quote wins.
    Quotes without a bookmaker are dropped: without it the row cannot be told apart from another book's."""
    rows = {}
    for q in quotes:
        if not q.get("bookmaker") or q.get("odds") is None or q.get("line") is None:
            continue
        row = {c: q[c] for c in QUOTE_KEY}
        row.update(odds=q["odds"], first_odds=q["odds"], first_seen=fetched_at, last_seen=fetched_at,
                   book_last_update=q.get("book_last_update"), event_id=q.get("event_id"), provider=provider)
        rows[tuple(row[c] for c in QUOTE_KEY)] = row
    return list(rows.values())


def quote_upsert_stmt(batch: list[dict]):
    """INSERT ... ON CONFLICT DO UPDATE: refresh the latest price and last_seen; first_odds/first_seen are kept."""
    stmt = insert(PropQuote).values(batch)
    return stmt.on_conflict_do_update(
        index_elements=QUOTE_KEY,
        set_={c: stmt.excluded[c] for c in ("odds", "last_seen", "book_last_update", "event_id", "provider")},
    )


async def upsert_prop_quotes(db: AsyncSession, quotes: list[dict], fetched_at: datetime.datetime | None = None) -> int:
    """Stores every bookmaker's quote from one PropLine fetch. Returns the number of rows written."""
    fetched_at = fetched_at or datetime.datetime.now(datetime.timezone.utc)
    rows = build_quote_rows(quotes, fetched_at)
    for i in range(0, len(rows), BATCH):
        await db.execute(quote_upsert_stmt(rows[i:i + BATCH]))
    await db.commit()
    return len(rows)


async def get_prop_quotes(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(PropQuote))
    return [{c.name: getattr(q, c.name) for c in PropQuote.__table__.columns} for q in result.scalars().all()]


async def get_quotes_for_games(db: AsyncSession, game_ids: list[int], player_id: int | None = None) -> list[PropQuote]:
    """Every stored quote for these games (optionally one player's), for the prediction log, scorer and prop board."""
    if not game_ids:
        return []
    stmt = select(PropQuote).where(PropQuote.game_id.in_(game_ids))
    if player_id is not None:
        stmt = stmt.where(PropQuote.player_id == player_id)
    return list((await db.execute(stmt)).scalars().all())


def latest_fetch(quotes: list) -> list:
    """The quotes seen in the latest fetch of their game: a book that pulled a market since keeps an older
    last_seen and drops out. One fetch writes one last_seen for every quote of a game."""
    newest = {}
    for q in quotes:
        newest[q.game_id] = max(newest.get(q.game_id, q.last_seen), q.last_seen)
    return [q for q in quotes if q.last_seen == newest[q.game_id]]
