from pydantic import BaseModel, Field
import datetime

class EventResponse(BaseModel):
    """Response model for upcoming games from Odds API"""
    event_id: str = Field(alias="id")
    home_team: str = Field(alias="home_team")
    away_team: str = Field(alias="away_team")
    commence_time: datetime.datetime = Field(alias="commence_time")

class PlayerPropsResponse(BaseModel):
    """Response model for player props from Odds API"""
    prop_type: str
    first_name: str
    last_name: str
    odds: float
    over_under: str
    # yes/no markets (anytime goal scorer) have no point; they settle like over/under 0.5
    line: float = 0.5
    # which book quoted this price (Odds API bookmaker key, e.g. "draftkings") and when that book last updated it
    bookmaker: str | None = None
    book_last_update: datetime.datetime | None = None