import pandas as pd
from sqlalchemy import select, case
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import SkaterGameLog, GoalieGameLog, Games, Player, TeamGameStats, GameOdds
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

async def load_team_stats(db: AsyncSession) -> pd.DataFrame:
    """Each team's totals per game (regular season and playoffs), named as in predictions.features.TEAM_STATS."""
    t = TeamGameStats
    stmt = select(
        t.game_id, t.team_tri_code.label("team"), t.opposing_team_tri_code.label("opponent"), t.season, t.game_date,
        _is_home(t.home_away), t.playoff,
        t.goals_for.label("gf"), t.goals_against.label("ga"), t.x_goals_for.label("xgf"), t.x_goals_against.label("xga"),
        t.shot_attempts_for.label("saf"), t.shot_attempts_against.label("saa"),
        t.x_goals_for_5v5.label("xgf5"), t.x_goals_against_5v5.label("xga5"),
        t.shot_attempts_for_5v5.label("cf5"), t.shot_attempts_against_5v5.label("ca5"),
        t.goals_for_5v5.label("gf5"), t.goals_against_5v5.label("ga5"),
    )
    df = _frame((await db.execute(stmt)).mappings().all())
    if not df.empty:
        stats = ["gf", "ga", "xgf", "xga", "saf", "saa", "xgf5", "xga5", "cf5", "ca5", "gf5", "ga5"]
        df[stats] = df[stats].astype(float)
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

async def load_game_odds(db: AsyncSession) -> pd.DataFrame:
    stmt = select(GameOdds.game_id, GameOdds.home_prob_novig, GameOdds.total_line)
    df = _frame((await db.execute(stmt)).mappings().all())
    return df if not df.empty else pd.DataFrame(columns=["game_id", "home_prob_novig", "total_line"])
