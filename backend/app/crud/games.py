from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import Games
from external.nhl.response_models import GameResponse
import datetime

async def upsert_scraped_games_from_schedule(db: AsyncSession, game_data: list[GameResponse]):
    """Upserts scraped game into local db Games table."""
    if not game_data:
        return
    data = [game.model_dump() for game in game_data]
    stmt = insert(Games).values(data)
    stmt = stmt.on_conflict_do_update(
        index_elements=['id'],
        set_={
            "home_team_tri_code": stmt.excluded.home_team_tri_code,
            "away_team_tri_code": stmt.excluded.away_team_tri_code,
            "season": stmt.excluded.season,
            "date": stmt.excluded.date,
            "venue": stmt.excluded.venue,
            "start_time": stmt.excluded.start_time,
            "home_team_logo": stmt.excluded.home_team_logo,
            "away_team_logo": stmt.excluded.away_team_logo,
            "home_score": stmt.excluded.home_score,
            "away_score": stmt.excluded.away_score,
            "game_state": stmt.excluded.game_state,
            "last_updated": datetime.datetime.now(datetime.timezone.utc),
        }
    )
    await db.execute(stmt)
    await db.commit()

# game states where a game is over and its score will no longer change
FINISHED_GAME_STATES = ("OFF", "FINAL")
# poll from shortly before puck drop until well past the longest realistic game
POLL_LEAD_TIME = datetime.timedelta(minutes=10)
POLL_MAX_GAME_LENGTH = datetime.timedelta(hours=8)

async def has_games_to_poll(db: AsyncSession, now: datetime.datetime | None = None) -> bool:
    """True if any game is about to start or in progress, i.e. its start time is within the
    lead time or in the past (up to the max game length) and it is not finished. The max
    game length keeps a postponed game stuck in a non-final state from being polled forever."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    result = await db.execute(
        select(Games.id).
        where(
            Games.start_time <= now + POLL_LEAD_TIME,
            Games.start_time >= now - POLL_MAX_GAME_LENGTH,
            Games.game_state.not_in(FINISHED_GAME_STATES)
        ).
        limit(1)
    )
    return result.first() is not None

async def get_team_last_5_games(db: AsyncSession, tri_code: str) -> list[Games]:
    """Fetches last 5 games from db for a team by tri code and season."""
    result = await db.execute(
        select(Games).
        where(
            (Games.home_team_tri_code == tri_code) | (Games.away_team_tri_code == tri_code),
            (Games.game_state == "OFF")
        ).
        order_by(Games.date.desc()).
        limit(5)
    )
    games = result.scalars().all()
    return games

async def get_date_most_recent_game_marked_as_future(db: AsyncSession, tri_code: str) -> datetime.datetime | None:
    """Fetches most recent game marked as future from db for a team by tri code."""
    result = await db.execute(
        select(Games.start_time).
        where(
            (Games.home_team_tri_code == tri_code) | (Games.away_team_tri_code == tri_code),
            (Games.game_state == "FUT")
        ).
        order_by(Games.date.asc()).
        limit(1)
    )
    game = result.scalar_one_or_none()
    return game

async def get_all_teams_most_recent_game_dates(db: AsyncSession) -> dict[str, int]:
    """Fetches most recent game played from db for all teams by tri code."""
    result = await db.execute(
        select(Games.home_team_tri_code, Games.date).
        where(Games.game_state == "OFF").
        order_by(Games.date.desc())
    )
    games = result.all()
    most_recent_game_dates = {}
    for tri_code, date in games:
        if tri_code not in most_recent_game_dates:
            most_recent_game_dates[tri_code] = date
    return most_recent_game_dates

async def get_next_game_info_by_tri_code(db: AsyncSession, tri_code: str) -> Games | None:
    """Fetches next game info from db for a team by tri code."""
    result = await db.execute(
        select(Games).
        where(
            (Games.home_team_tri_code == tri_code) | (Games.away_team_tri_code == tri_code),
            (Games.game_state == "FUT")
        ).
        order_by(Games.date.asc()).
        limit(1)
    )
    game = result.scalar_one_or_none()
    return game

async def get_next_n_games_info_by_tri_code(db: AsyncSession, tri_code: str, n: int, offset: int = 0) -> list[Games]:
    """Fetches next n games info from db for a team by tri code."""
    result = await db.execute(
        select(Games).
        where(
            (Games.home_team_tri_code == tri_code) | (Games.away_team_tri_code == tri_code),
            (Games.game_state == "FUT")
        ).
        order_by(Games.date.asc()).
        offset(offset).
        limit(n)
    )
    games = result.scalars().all()
    return games

async def check_if_games_in_db(db: AsyncSession, game_ids: list[int]) -> list[int]:
    """Checks if games are in db by game IDs."""
    result = await db.execute(
        select(Games.id).where(Games.id.in_(game_ids))
    )
    existing_game_ids = result.scalars().all()
    return existing_game_ids

async def get_all_games_for_date(db: AsyncSession, date: int) -> list[Games]:
    """Fetches all games from db for date."""
    result = await db.execute(
        select(Games).
        where(
            Games.date == date
        ).
        order_by(Games.start_time.asc())
    )
    games = result.scalars().all()
    return games

async def get_game_by_id(db: AsyncSession, game_id: int) -> Games | None:
    """Fetches a single game by its ID."""
    result = await db.execute(select(Games).where(Games.id == game_id))
    return result.scalar_one_or_none()

async def delete_games_for_team_in_the_future(db: AsyncSession, tri_code: str):
    """Deletes all games for a team in the future."""
    stmt = delete(Games).where(
            (Games.home_team_tri_code == tri_code) | (Games.away_team_tri_code == tri_code),
            (Games.game_state == "FUT")
        )
    await db.execute(stmt)
    await db.commit()