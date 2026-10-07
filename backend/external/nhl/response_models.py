from pydantic import BaseModel, Field, field_validator
import datetime

class TeamResponse(BaseModel):
    """NHL API Response for Team Information"""
    current_name: str = Field(alias="fullName")
    franchise_id: int = Field(alias="franchiseId")
    tri_code: str = Field(alias="triCode")
    class Config:
        validate_by_name = True

class TeamHistoryResponse(BaseModel):
    """NHL API Response for Team with just History Information extracted"""
    id: int = Field(alias="id")
    name: str = Field(alias="fullName")
    tri_code: str = Field(alias="triCode")

class PlayerResponse(BaseModel):
    """NHL API Response for Player Information"""
    id: int = Field(alias="id")
    headshot: str | None = Field(alias="headshot")
    first_name: str = Field(alias="firstName")
    last_name: str = Field(alias="lastName")
    number: int | None = Field(default=None, alias="sweaterNumber")
    position: str | None = Field(default=None, alias="positionCode")
    shoots_catches: str | None = Field(default=None, alias="shootsCatches")
    birth_date: datetime.date | None = Field(default=None, alias="birthDate")
    
    # to get the english names 
    @field_validator("first_name", "last_name", mode="before")
    def extract_names(cls, v) -> str:
        if isinstance(v, dict) and "default" in v:
            return v["default"]
        return v

    class Config:
        validate_by_name = True

class PlayerLandingResponse(BaseModel):
    """NHL API Response for Player Landing Page Information"""
    # kept separate from PlayerResponse in case info changes later on in time
    id: int = Field(alias="playerId")
    headshot: str | None = Field(alias="headshot")
    first_name: str = Field(alias="firstName")
    last_name: str = Field(alias="lastName")
    number: int | None = Field(default=None, alias="sweaterNumber")
    position: str | None = Field(default=None, alias="positionCode")
    shoots_catches: str | None = Field(default=None, alias="shootsCatches")
    birth_date: datetime.date | None = Field(default=None, alias="birthDate")
    
    # to get the english names 
    @field_validator("first_name", "last_name", mode="before")
    def extract_names(cls, v) -> str:
        if isinstance(v, dict) and "default" in v:
            return v["default"]
        return v

    class Config:
        validate_by_name = True

class GameResponse(BaseModel):
    """NHL API Response for Game Information"""
    id: int = Field(alias="id")
    home_team_tri_code: str = Field(alias="homeTeam")
    away_team_tri_code: str = Field(alias="awayTeam")
    season: int = Field(alias="season")
    date: int = Field(alias="gameDate")
    venue: str = Field(alias="venue")
    start_time: datetime.datetime = Field(alias="startTimeUTC")
    home_team_logo: str | None = Field(alias="homeTeam")
    away_team_logo: str | None = Field(alias="awayTeam")
    home_score: int | None = Field(alias="homeTeam")
    away_score: int | None = Field(alias="awayTeam")
    game_state: str = Field(alias="gameState")

    # get team tri codes
    @field_validator("home_team_tri_code", "away_team_tri_code", mode="before")
    def extract_tri_codes(cls, v) -> str:
        if isinstance(v, dict) and "abbrev" in v:
            return v["abbrev"]
        return v

    #clean str date "YYYY-MM-DD" to YYYYMMDD int
    @field_validator("date", mode="before")
    def convert_date(cls, v) -> int:
        if isinstance(v, str):
            try:
                dt = datetime.datetime.strptime(v, "%Y-%m-%d")
                return int(dt.strftime("%Y%m%d"))
            except ValueError:
                raise ValueError(f"Invalid date format: {v}. Expected 'YYYY-MM-DD'.")
        return v
    
    # get team logos    
    @field_validator("home_team_logo", "away_team_logo", mode="before")
    def extract_logos(cls, v) -> str | None:
        if isinstance(v, dict) and "logo" in v:
            return v["logo"]
        return None
    
    # get team scores
    @field_validator("home_score", "away_score", mode="before")
    def extract_scores(cls, v) -> int | None:
        if isinstance(v, dict) and "score" in v:
            return v["score"]
        return None
    
    # get venue name
    @field_validator("venue", mode="before")
    def extract_venue(cls, v) -> str:
        if isinstance(v, dict) and "default" in v:
            return v["default"]
        return v
    
    class Config:
        validate_by_name = True
        frozen = True


class GameOdds(BaseModel):
    """Cleaned NHL API Response for Odds Information"""
    game_id: int
    home_moneyline: float
    away_moneyline: float

class GameGoalie(BaseModel):
    """A goalie on one team's roster for a game (from gamecenter landing / play-by-play)."""
    player_id: int
    team: str                      # NHL tri code
    first_name: str | None = None
    last_name: str | None = None
    sweater_number: int | None = None
    # True/False once the play-by-play rosterSpots (dressed players) are posted, None before
    dressed: bool | None = None


class StarterPick(BaseModel):
    """One team's starting goalie for a game, as stored in game_starters."""
    game_id: int
    team: str
    player_id: int
    status: str                    # "actual" | "confirmed" | "probable" | "projected"
    source: str                    # "espn" (pre-game picks) or "nhl" (actual starters)
