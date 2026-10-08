from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select, or_, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import Games, Player, Team
from external.nhl.response_models import TeamResponse
import datetime

async def upsert_team(db: AsyncSession, team_data: TeamResponse):
    #change to bulk upsert later
    """Upserts scraped team into local db Teams table."""
    data = team_data.model_dump()
    stmt = insert(Team).values(**data)
    stmt = stmt.on_conflict_do_update(
        index_elements=['tri_code'],
        set_={
            "franchise_id": stmt.excluded.franchise_id,
            "current_name": stmt.excluded.current_name,
        }
    )
    await db.execute(stmt)
    await db.commit()

async def check_tri_code_exists(db: AsyncSession, tri_code: str) -> bool:
    """Checks if a team with the given tri code exists in the database."""
    result = await db.execute(select(Team).where(Team.tri_code == tri_code))
    team = result.scalar_one_or_none()
    return team is not None

async def get_all_tri_codes_update_roster(db: AsyncSession) -> list[str]:
    """Tri codes of active teams whose roster was last updated more than a day ago. Active = has a game in the
    last year or scheduled: relocated teams (ATL, PHX, ARI) stay in the table for old games but have no roster to
    fetch (the NHL returns 404), and their roster_last_updated is never set, so they were retried every run."""
    since = int((datetime.date.today() - datetime.timedelta(days=365)).strftime("%Y%m%d"))
    active = select(Games.home_team_tri_code).where(Games.date >= since).union(
        select(Games.away_team_tri_code).where(Games.date >= since))
    result = await db.execute(
        select(Team.tri_code).where(
            or_(
                Team.roster_last_updated.is_(None),
                Team.roster_last_updated < datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
            ),
            Team.tri_code.in_(active),
        )
    )
    tri_codes = result.scalars().all()
    return tri_codes

async def get_all_tri_codes_in_db(db: AsyncSession) -> list[str]:
    """Fetches all team tri codes from the database."""
    result = await db.execute(select(Team.tri_code))
    tri_codes = result.scalars().all()
    return tri_codes

async def update_team_roster_last_updated(db: AsyncSession, tri_code: str):
    """Updates the roster_last_updated field for a team."""
    stmt = (
        update(Team).
        where(Team.tri_code == tri_code).
        values(roster_last_updated=datetime.datetime.now(datetime.timezone.utc))
    )
    await db.execute(stmt)
    await db.commit()

async def get_team_by_tri_code(db: AsyncSession, tri_code: str) -> Team | None:
    """Fetches team basic info from db by tri code."""
    result = await db.execute(select(Team).where(Team.tri_code == tri_code))
    team = result.scalar_one_or_none()
    return team


async def get_team_current_roster(db: AsyncSession, tri_code: str) -> list[Player] | None:
    """Fetches team roster from db by tri code."""
    stmt = (
        select(Team)
        .options(selectinload(Team.current_players))
        .where(Team.tri_code == tri_code)
    )
    result = await db.execute(stmt)
    team = result.scalar_one_or_none()
    return team.current_players if team else None

async def get_all_teams(db: AsyncSession) -> list[Team] | None:
    """Fetches all teams from the database."""
    result = await db.execute(select(Team))
    teams = result.scalars().all()
    return teams

async def search_teams_by_name(db: AsyncSession, query: str, limit: int = 3) -> list[Team]:
    """Searches teams by name"""
    search_term = f"%{query}%"
    result = await db.execute(
        select(Team).where(
            or_(
                Team.current_name.ilike(search_term),
                Team.tri_code.ilike(search_term)
            )
        )
        .order_by(Team.current_name.asc())
        .limit(limit)
    )
    return list(result.scalars().all())
        