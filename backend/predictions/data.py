import pandas as pd
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import SkaterGameLog, GoalieGameLog, Games, Player
from app.crud.games import FINISHED_GAME_STATES

def _frame(rows) -> pd.DataFrame:
    return pd.DataFrame([dict(r) for r in rows])

def _is_home(col):
    return case((col == "HOME", 1.0), else_=0.0).label("is_home")

async def load_skater_logs(db: AsyncSession, player_ids: list[int] | None = None) -> pd.DataFrame:
    stmt = (
        select(
            SkaterGameLog.game_id, SkaterGameLog.player_id, SkaterGameLog.season, SkaterGameLog.game_date,
            SkaterGameLog.player_team_tricode.label("team"), SkaterGameLog.opposing_team_tricode.label("opponent"),
            _is_home(SkaterGameLog.home_away), Player.position,
            SkaterGameLog.goals, SkaterGameLog.primary_assists, SkaterGameLog.secondary_assists, SkaterGameLog.points,
            SkaterGameLog.x_goals, SkaterGameLog.toi, SkaterGameLog.shot_attempts, SkaterGameLog.high_danger_shots,
            SkaterGameLog.on_ice_x_goals_percentage, SkaterGameLog.game_score,
        )
        .join(Player, Player.id == SkaterGameLog.player_id)
    )
    if player_ids is not None:
        stmt = stmt.where(SkaterGameLog.player_id.in_(player_ids))
    return _frame((await db.execute(stmt)).mappings().all())

async def load_goalie_logs(db: AsyncSession, player_ids: list[int] | None = None) -> pd.DataFrame:
    stmt = select(
        GoalieGameLog.game_id, GoalieGameLog.player_id, GoalieGameLog.season, GoalieGameLog.game_date,
        GoalieGameLog.player_team_tricode.label("team"), GoalieGameLog.opposing_team_tricode.label("opponent"),
        _is_home(GoalieGameLog.home_away), GoalieGameLog.toi,
        GoalieGameLog.goals_against, GoalieGameLog.x_goals_against, GoalieGameLog.sog, GoalieGameLog.x_sog,
        GoalieGameLog.flurry_adjusted_x_goals, GoalieGameLog.high_danger_x_goals, GoalieGameLog.high_danger_shots,
        GoalieGameLog.rebounds, GoalieGameLog.x_rebounds,
    )
    if player_ids is not None:
        stmt = stmt.where(GoalieGameLog.player_id.in_(player_ids))
    return _frame((await db.execute(stmt)).mappings().all())

async def load_team_offense(db: AsyncSession) -> pd.DataFrame:
    """Each team's offensive totals per game, summed from its skaters (complete, unlike goalie logs)."""
    stmt = (
        select(
            SkaterGameLog.game_id, SkaterGameLog.player_team_tricode.label("team"),
            SkaterGameLog.opposing_team_tricode.label("opponent"), SkaterGameLog.season, SkaterGameLog.game_date,
            _is_home(SkaterGameLog.home_away),
            func.sum(SkaterGameLog.goals).label("gf"), func.sum(SkaterGameLog.x_goals).label("xgf"),
            func.sum(SkaterGameLog.shot_attempts).label("saf"), func.sum(SkaterGameLog.high_danger_shots).label("hdf"),
        )
        .group_by(SkaterGameLog.game_id, SkaterGameLog.player_team_tricode, SkaterGameLog.opposing_team_tricode,
                  SkaterGameLog.season, SkaterGameLog.game_date, SkaterGameLog.home_away)
    )
    df = _frame((await db.execute(stmt)).mappings().all())
    if not df.empty:
        df[["gf", "xgf", "saf", "hdf"]] = df[["gf", "xgf", "saf", "hdf"]].astype(float)
    return df

async def load_games(db: AsyncSession) -> pd.DataFrame:
    """All scheduled and played games. `season` uses MoneyPuck's start-year format (20252026 -> 2025);
    scores are only kept for finished games so live and future games never count as results."""
    stmt = select(Games.id, Games.season, Games.date, Games.home_team_tri_code, Games.away_team_tri_code,
                  Games.home_score, Games.away_score, Games.game_state)
    df = _frame((await db.execute(stmt)).mappings().all())
    if df.empty:
        return df
    df["season"] = df["season"] // 10000
    finished = df["game_state"].isin(FINISHED_GAME_STATES)
    df[["home_score", "away_score"]] = df[["home_score", "away_score"]].astype(float).where(finished)
    return df.drop(columns="game_state")
