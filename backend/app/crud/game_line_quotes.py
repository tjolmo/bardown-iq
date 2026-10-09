import datetime
from collections import defaultdict
from statistics import median

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from external.propline.books import CONSENSUS_BOOKS
from ..models import GameLineQuote

LINE_KEY = ["game_id", "market", "side", "line", "bookmaker"]
BATCH = 2000


def build_line_rows(quotes: list[dict], fetched_at: datetime.datetime) -> list[dict]:
    """One row per primary key (ON CONFLICT cannot touch a row twice in one statement); the last quote wins."""
    rows = {}
    for q in quotes:
        if not q.get("bookmaker") or q.get("odds") is None or q.get("line") is None:
            continue
        row = {c: q[c] for c in LINE_KEY}
        row.update(odds=q["odds"], first_odds=q["odds"], first_seen=fetched_at, last_seen=fetched_at,
                   book_last_update=q.get("book_last_update"), event_id=q.get("event_id"))
        rows[tuple(row[c] for c in LINE_KEY)] = row
    return list(rows.values())


def line_upsert_stmt(batch: list[dict]):
    """INSERT ... ON CONFLICT DO UPDATE: refresh the latest price and last_seen; first_odds/first_seen are kept."""
    stmt = insert(GameLineQuote).values(batch)
    return stmt.on_conflict_do_update(
        index_elements=LINE_KEY,
        set_={c: stmt.excluded[c] for c in ("odds", "last_seen", "book_last_update", "event_id")},
    )


async def upsert_game_line_quotes(db: AsyncSession, quotes: list[dict], fetched_at: datetime.datetime | None = None) -> int:
    """Stores every book's game lines from one PropLine fetch. Returns the number of rows written."""
    fetched_at = fetched_at or datetime.datetime.now(datetime.timezone.utc)
    rows = build_line_rows(quotes, fetched_at)
    for i in range(0, len(rows), BATCH):
        await db.execute(line_upsert_stmt(rows[i:i + BATCH]))
    await db.commit()
    return len(rows)


def _median_american(prices: list[float]) -> int:
    """Median of American prices taken on implied probability (a plain median of -105 and +105 would be 0)."""
    probs = [100 / (p + 100) if p > 0 else -p / (-p + 100) for p in prices]
    m = median(probs)
    return round(-100 * m / (1 - m)) if m >= 0.5 else round(100 * (1 - m) / m)


def summarize_moneylines(quotes: list) -> dict[int, dict]:
    """game_id -> the site's moneyline from the latest fetch of each game's h2h quotes: the median price and the
    best price (and its book) per side among the consensus books. The exchanges are left out of both: their asks
    carry almost no vig, so they would be the "best" price nearly every time."""
    newest = {}
    for q in quotes:
        newest[q.game_id] = max(newest.get(q.game_id, q.last_seen), q.last_seen)
    sides: dict[int, dict] = defaultdict(lambda: defaultdict(list))
    for q in quotes:
        if q.market == "h2h" and q.last_seen == newest[q.game_id] and q.side in ("home", "away"):
            sides[q.game_id][q.side].append(q)
    out = {}
    for gid, by_side in sides.items():
        home = [q for q in by_side["home"] if q.bookmaker in CONSENSUS_BOOKS]
        away = [q for q in by_side["away"] if q.bookmaker in CONSENSUS_BOOKS]
        if not home or not away:
            continue
        best_home = max(home, key=lambda q: q.odds)
        best_away = max(away, key=lambda q: q.odds)
        out[gid] = {"home": _median_american([q.odds for q in home]), "away": _median_american([q.odds for q in away]),
                    "best_home": int(best_home.odds), "best_home_book": best_home.bookmaker,
                    "best_away": int(best_away.odds), "best_away_book": best_away.bookmaker,
                    "n_books": len({q.bookmaker for q in home} & {q.bookmaker for q in away})}
    return out


async def get_moneylines(db: AsyncSession, game_ids: list[int]) -> dict[int, dict]:
    """The site's moneyline per game (summarize_moneylines) for these games; games without PropLine lines are absent."""
    if not game_ids:
        return {}
    stmt = select(GameLineQuote).where(GameLineQuote.game_id.in_(game_ids), GameLineQuote.market == "h2h")
    return summarize_moneylines(list((await db.execute(stmt)).scalars().all()))
