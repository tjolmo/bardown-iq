from pydantic import BaseModel, ConfigDict, Field
import datetime

class EventResponse(BaseModel):
    """An upcoming game from PropLine's events endpoint"""
    # PropLine documents string ids but its single-event path takes an integer: accept either
    model_config = ConfigDict(coerce_numbers_to_str=True)
    event_id: str = Field(alias="id")
    home_team: str = Field(alias="home_team")
    away_team: str = Field(alias="away_team")
    commence_time: datetime.datetime = Field(alias="commence_time")

class PlayerPropsResponse(BaseModel):
    """One book's price for one side of a player prop, already mapped to the app's market keys"""
    prop_type: str
    first_name: str
    last_name: str
    odds: float
    over_under: str
    # yes/no markets (anytime goal scorer, 1+ points) have no point; they settle like over/under 0.5
    line: float = 0.5
    # which book quoted this price (bookmaker key, e.g. "draftkings") and when that book last updated it
    bookmaker: str | None = None
    book_last_update: datetime.datetime | None = None
    # the NHL's own player id when PropLine carries one ("nhl:8479318" -> 8479318): matches without names
    nhl_player_id: int | None = None

class GameLineResponse(BaseModel):
    """One book's price for one side of a game line: h2h (moneyline), spreads (puck line) or totals"""
    event_id: str
    market: str                 # "h2h" / "spreads" / "totals"
    side: str                   # "home" / "away" for h2h and spreads, "over" / "under" for totals
    line: float = 0.0           # the spread for the side (e.g. -1.5), the total, 0 for h2h
    odds: float
    bookmaker: str
    book_last_update: datetime.datetime | None = None
