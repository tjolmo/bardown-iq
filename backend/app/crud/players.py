from app.models import GoalieGameLog
from app.models import SkaterGameLog
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import Player
from external.nhl.response_models import PlayerResponse, PlayerLandingResponse
import datetime

async def upsert_scraped_player(db: AsyncSession, player_data: PlayerResponse|PlayerLandingResponse, tri_code: str | None = None):
    # Need to modify to bulk upsert
    """Upserts scraped player into local db Players table."""
    data = player_data.model_dump()
    data["current_team_tri_code"] = tri_code
    stmt = insert(Player).values(**data)
    stmt = stmt.on_conflict_do_update(
        index_elements=['id'],
        set_={
            "current_team_tri_code": func.coalesce(stmt.excluded.current_team_tri_code, Player.current_team_tri_code),
            "headshot": stmt.excluded.headshot,
            "first_name": stmt.excluded.first_name,
            "last_name": stmt.excluded.last_name,
            "number": stmt.excluded.number,
            "position": stmt.excluded.position,
            "shoots_catches": stmt.excluded.shoots_catches,
        }
    )
    await db.execute(stmt)
    await db.commit()

async def get_skater_by_id(db: AsyncSession, player_id: int) -> Player | None:
    """Fetches player from db by ID."""
    result = await db.execute(select(Player).where(Player.id == player_id, Player.position != "G"))
    player = result.scalar_one_or_none()
    return player

async def get_goalie_by_id(db: AsyncSession, player_id: int) -> Player | None:
    """Fetches goalie from db by ID."""
    result = await db.execute(select(Player).where(Player.id == player_id, Player.position == "G"))
    player = result.scalar_one_or_none()
    return player

async def get_player_by_id(db: AsyncSession, player_id: int) -> Player | None:
    """Fetches player from db by ID."""
    result = await db.execute(select(Player).where(Player.id == player_id))
    player = result.scalar_one_or_none()
    return player

async def update_player_game_log_last_updated(db: AsyncSession, player_id: int):
    """Updates the game_log_last_updated field for a player."""
    stmt = (
        update(Player).
        where(Player.id == player_id).
        values(game_log_last_updated=datetime.datetime.now(datetime.timezone.utc))
    )
    await db.execute(stmt)
    await db.commit()

async def get_all_skater_ids_and_teams(db: AsyncSession) -> list[tuple[int, str]]:
    """Fetches all skater IDs w team from the database."""
    result = await db.execute(
        select(Player.id, Player.current_team_tri_code).where(
            Player.position != "G"
        )
    )
    player_ids = result.all()
    return player_ids

async def get_all_skaters_on_a_roster(db: AsyncSession) -> list[tuple[int, str]]:
    """Fetches all skaters on a roster for a team by tri code."""
    result = await db.execute(
        select(Player.id, Player.current_team_tri_code).where(
            Player.current_team_tri_code != None,
            Player.position != "G"
        )
    )
    players = result.all()
    return players

async def get_all_goalies_on_a_roster(db: AsyncSession) -> list[tuple[int, str]]:
    """Fetches all goalies on a roster for a team by tri code."""
    result = await db.execute(
        select(Player.id, Player.current_team_tri_code).where(
            Player.current_team_tri_code != None,
            Player.position == "G"
        )
    )
    players = result.all()
    return players

async def get_all_goalie_ids_and_teams(db: AsyncSession) -> list[tuple[int, str]]:
    """Fetches all goalie IDs w team from the database."""
    result = await db.execute(
        select(Player.id, Player.current_team_tri_code).where(
            Player.position == "G"
        )
    )
    player_ids = result.all()
    return player_ids

async def get_players_not_in_db(db: AsyncSession, player_ids: list[int]) -> list[int]:
    """Fetches player IDs not in the database."""
    result = await db.execute(
        select(Player.id).where(Player.id.in_(player_ids))
    )
    existing_player_ids = result.scalars().all()
    return [player_id for player_id in player_ids if player_id not in existing_player_ids]


async def set_all_other_players_current_team_tri_code_to_null(db: AsyncSession, tri_code: str, player_ids_on_current_roster: list[int]):
    """Sets current_team_tri_code to null for players assigned to tri_code who are not on its current roster."""
    stmt = (
        update(Player).
        where(
            Player.current_team_tri_code == tri_code,
            Player.id.not_in(player_ids_on_current_roster),
        ).
        values(current_team_tri_code=None)
    )
    await db.execute(stmt)
    await db.commit()

async def search_players_by_name(db: AsyncSession, query: str, limit: int = 3) -> list[Player]:
    """Searches players by first/last name"""
    search_term = f"%{query}%"
    result = await db.execute(
        select(Player).where(
        (Player.first_name + " " + Player.last_name).ilike(search_term)
        )
        .order_by(Player.current_team_tri_code.asc())
        .limit(limit)
    )
    return list(result.scalars().all())

async def get_player_current_team_tri_code(db: AsyncSession, player_id: int) -> str | None:
    """Fetches the current team tri code for a player."""
    result = await db.execute(
        select(Player.current_team_tri_code).where(Player.id == player_id)
    )
    player_tri_code = result.scalar_one_or_none()
    return player_tri_code

async def get_top_n_skaters(db: AsyncSession, n: int, season: int) -> list[Player]:
    """Fetches the top n skaters based on points from the database."""
    result = await db.execute(
        select(Player).where(
            Player.position != "G",
            Player.current_team_tri_code != None
        )
        .join(SkaterGameLog, SkaterGameLog.player_id == Player.id)
        .where(SkaterGameLog.season == season) 
        .group_by(Player.id)
        .order_by(func.sum(SkaterGameLog.points).desc())
        .limit(n)
    )
    return result.scalars().all()

async def get_top_n_goalies(db: AsyncSession, n: int, season: int) -> list[Player]:
    """Fetches the top n goalies based on sv% from the database."""
    result = await db.execute(
        select(Player).where(
            Player.position == "G",
            Player.current_team_tri_code != None
        )
        .join(GoalieGameLog, GoalieGameLog.player_id == Player.id)
        .where(GoalieGameLog.season == season) 
        .group_by(Player.id)
        .order_by(1-(func.sum(GoalieGameLog.goals_against)/func.sum(GoalieGameLog.sog)).desc())
        .having(func.count(GoalieGameLog.player_id) >= 5)
        .limit(n)
    )
    return result.scalars().all()

async def get_player_by_name_and_roster_options(db: AsyncSession, first_name: str, last_name: str, potential_tri_codes:list[str]) -> Player | None:
    """Fetches player from db by name."""
    result = await db.execute(
        select(Player).where(
            Player.first_name == first_name,
            Player.last_name == last_name,
            Player.current_team_tri_code.in_(potential_tri_codes)
        )
    )
    return result.scalar_one_or_none()
    
    