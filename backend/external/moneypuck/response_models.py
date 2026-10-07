import math
from pydantic import BaseModel, Field, field_validator
from datetime import datetime

class SkaterGameLogResponse(BaseModel):
    """Response model for a Skater's game log data from MoneyPuck API"""
    game_id: int = Field(alias="gameId")
    player_id: int = Field(alias="playerId")
    season: int = Field(alias="season")
    name: str = Field (alias="name")
    home_away: str = Field(alias="home_or_away")
    player_team_tricode: str = Field(alias="playerTeam")
    opposing_team_tricode: str = Field(alias="opposingTeam")
    game_date: int = Field(alias="gameDate")
    goals: int = Field(alias="I_F_goals")
    primary_assists: int = Field(alias="I_F_primaryAssists")
    secondary_assists: int = Field(alias="I_F_secondaryAssists")
    points: int = Field(alias="I_F_points")
    x_goals: float = Field(alias="I_F_xGoals")
    toi: float = Field(alias="icetime")
    high_danger_shots: int = Field(alias="I_F_highDangerShots")
    shot_attempts: int = Field(alias="I_F_shotAttempts")
    on_ice_x_goals_percentage: float = Field(alias="onIce_xGoalsPercentage")
    game_score: float = Field(alias="gameScore")
    # optional so the per-player career scrape (which doesn't join these) still validates
    shots_on_goal: int | None = Field(default=None, alias="I_F_shotsOnGoal")
    pp_toi: float | None = Field(default=None, alias="pp_icetime")  # 5on4 ice time, seconds
    pp_points: int | None = Field(default=None, alias="pp_I_F_points")  # 5on4 points

    @field_validator("shots_on_goal", "pp_toi", "pp_points", mode="before")
    @classmethod
    def _nan_to_none(cls, v):
        return None if isinstance(v, float) and math.isnan(v) else v

    class Config:
        validate_by_name = True

class GoalieGameLogResponse(BaseModel):
    """Response model for a Goalie's game log data from MoneyPuck API"""
    game_id: int = Field(alias="gameId")
    player_id: int = Field(alias="playerId")
    season: int = Field(alias="season")
    name: str = Field (alias="name")
    home_away: str = Field(alias="home_or_away")
    player_team_tricode: str = Field(alias="playerTeam")
    opposing_team_tricode: str = Field(alias="opposingTeam")
    game_date: int = Field(alias="gameDate")
    toi: float = Field(alias="icetime")
    x_goals_against: float = Field(alias="xGoals")
    goals_against: int = Field(alias="goals")
    unblocked_shot_attempts: int = Field(alias="unblocked_shot_attempts")
    x_rebounds: float = Field(alias="xRebounds")
    rebounds: int = Field(alias="rebounds")
    x_freeze: float = Field(alias="xFreeze")
    freeze: int = Field(alias="freeze")
    x_sog: float = Field(alias="xOnGoal")
    sog: int = Field(alias="ongoal")
    x_play_stopped: float = Field(alias="xPlayStopped")
    play_stopped: int = Field(alias="playStopped")
    x_play_continued_in_zone: float = Field(alias="xPlayContinuedInZone")
    x_play_continued_outside_zone: float = Field(alias="xPlayContinuedOutsideZone")
    flurry_adjusted_x_goals: float = Field(alias="flurryAdjustedxGoals")
    low_danger_shots: int = Field(alias="lowDangerShots")
    medium_danger_shots: int = Field(alias="mediumDangerShots")
    high_danger_shots: int = Field(alias="highDangerShots")
    low_danger_x_goals: float = Field(alias="lowDangerxGoals")
    medium_danger_x_goals: float = Field(alias="mediumDangerxGoals")
    high_danger_x_goals: float = Field(alias="highDangerxGoals")
    blocked_shot_attempts: int = Field(alias="blocked_shot_attempts")
    penality_minutes: int = Field(alias="penalityMinutes")
    penalties: int = Field(alias="penalties")

    class Config:
        validate_by_name = True