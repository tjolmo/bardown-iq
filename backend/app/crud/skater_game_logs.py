from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import SkaterGameLog
from external.moneypuck.response_models import SkaterGameLogResponse
import datetime

async def upsert_scraped_game_logs(db: AsyncSession, game_logs_data: list[SkaterGameLogResponse]):
    """Upserts scraped player game log into local db PlayerGameLogs table."""
    if not game_logs_data:
        return
    for i in range(0, len(game_logs_data), 1000):
        batch = [log.model_dump() for log in game_logs_data[i : i + 1000]]
        stmt = insert(SkaterGameLog).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=['game_id', 'player_id'],
            set_={
                "name": stmt.excluded.name,
                "season": stmt.excluded.season,
                "home_away": stmt.excluded.home_away,
                "player_team_tricode": stmt.excluded.player_team_tricode,
                "opposing_team_tricode": stmt.excluded.opposing_team_tricode,
                "game_date": stmt.excluded.game_date,
                "goals": stmt.excluded.goals,
                "primary_assists": stmt.excluded.primary_assists,
                "secondary_assists": stmt.excluded.secondary_assists,
                "points": stmt.excluded.points,
                "x_goals": stmt.excluded.x_goals,
                "toi": stmt.excluded.toi,
                "high_danger_shots": stmt.excluded.high_danger_shots,
                "shot_attempts": stmt.excluded.shot_attempts,
                "on_ice_x_goals_percentage": stmt.excluded.on_ice_x_goals_percentage,
                "game_score": stmt.excluded.game_score,
                "shots_on_goal": func.coalesce(stmt.excluded.shots_on_goal, SkaterGameLog.shots_on_goal),
                "pp_toi": func.coalesce(stmt.excluded.pp_toi, SkaterGameLog.pp_toi),
                "pp_points": func.coalesce(stmt.excluded.pp_points, SkaterGameLog.pp_points),
                "hits": func.coalesce(stmt.excluded.hits, SkaterGameLog.hits),
                "blocked_shots": func.coalesce(stmt.excluded.blocked_shots, SkaterGameLog.blocked_shots),
            }
        )
        await db.execute(stmt)
    await db.commit()

async def get_player_game_log_by_game_and_player_id(db: AsyncSession, game_id: int, player_id: int) -> SkaterGameLog | None:
    """Fetches player game log from db by game ID and player ID."""
    result = await db.execute(
        select(SkaterGameLog).where(
            SkaterGameLog.game_id == game_id,
            SkaterGameLog.player_id == player_id
        )
    )
    game_log = result.scalar_one_or_none()
    return game_log

async def get_player_most_recent_game_date_and_last_updated(db: AsyncSession, player_id: int) -> tuple[int, datetime.datetime] | None:
    """Fetches most recent game date from db for a player by player ID."""
    result = await db.execute(
        select(SkaterGameLog.game_date, SkaterGameLog.last_updated).
        where(SkaterGameLog.player_id == player_id).
        order_by(SkaterGameLog.game_date.desc()).
        limit(1)
    )
    game_date_and_last_updated = result.one_or_none()
    return game_date_and_last_updated

async def get_latest_logged_season(db: AsyncSession) -> int | None:
    """Start year of the latest season with game logs (MoneyPuck's `season`, e.g. 2026 for 2026-27)."""
    return (await db.execute(select(func.max(SkaterGameLog.season)))).scalar()

async def get_skater_season_basic_stats_from_db(db: AsyncSession, player_id: int, season: int) -> dict | None:
    """Fetches skater season stats from db for a player by player ID and season."""
    result = await db.execute(
        select(
            SkaterGameLog.goals,
            SkaterGameLog.primary_assists,
            SkaterGameLog.secondary_assists,
            SkaterGameLog.points,
        ).
        where(
            SkaterGameLog.player_id == player_id,
            SkaterGameLog.season == season
        )
    )
    season_stats = result.all()
    #accumulate stats for season
    if season_stats:
        games = len(season_stats)
        goals = sum([stat[0] for stat in season_stats])
        assists = sum([stat[1] + stat[2] for stat in season_stats])
        points = sum([stat[3] for stat in season_stats])
        return {
            "games": games,
            "goals": goals,
            "assists": assists,
            "points": points
        }
    return None

async def get_skater_last_5_basic_stats_from_db(db: AsyncSession, player_id: int) -> list[dict] | None:
    """Fetches skater last 5 games stats from db for a player by player ID."""
    result = await db.execute(
        select(
            SkaterGameLog.game_date,
            SkaterGameLog.opposing_team_tricode,
            SkaterGameLog.goals,
            SkaterGameLog.primary_assists,
            SkaterGameLog.secondary_assists,
            SkaterGameLog.points,
            SkaterGameLog.home_away,
        ).where(SkaterGameLog.player_id == player_id).order_by(SkaterGameLog.game_date.desc()).limit(5)
    )
    last_5 = result.all()
    if last_5:
        return [
            {
                "game_date": game[0],
                "opposing_team_tricode": game[1],
                "goals": game[2],
                "assists": game[3] + game[4],
                "points": game[5],
                "home_away": game[6]
            } for game in last_5
        ]
    return None
