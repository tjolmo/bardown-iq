import datetime

from pydantic import BaseModel

class Last5GameInfoOut(BaseModel):
    """Output model for a team's last 5 games info"""
    game_id: int
    date: int
    home_team_tri_code: str
    away_team_tri_code: str
    home_score: int | None
    away_score: int | None

    class Config:
        from_attributes = True

class TeamBasicInfoOut(BaseModel):
    """Output model for a team's basic info"""
    name: str
    tricode: str
    logoUrl: str | None

class TeamGameLiveOut(BaseModel):
    """A started game's period and clock, from NHL's score feed (polled every LIVE_SCORES_POLL_MINUTES)"""
    period: int | None = None
    periodType: str | None = None        # REG / OT / SO
    secondsRemaining: int | None = None  # of the period, or of the intermission when inIntermission
    timeRemaining: str | None = None     # secondsRemaining as "MM:SS"
    inIntermission: bool = False
    clockRunning: bool = False
    asOf: datetime.datetime              # when the feed was fetched; the game clock is as of then

class TeamGameEdgeOut(BaseModel):
    """The side the model likes against the market: model win probability minus the no-vig moneyline probability"""
    tri_code: str
    side: str        # home / away
    points: float    # percentage points, one decimal

class TeamScheduledGameInfoOut(BaseModel):
    """Output model for a team's upcoming game info"""
    id: int
    date: str
    homeTeam: TeamBasicInfoOut
    awayTeam: TeamBasicInfoOut
    awayScore: int | None
    homeScore: int | None
    time: datetime.datetime
    venue: str
    gameState: str
    predictions: TeamGamePredictionOut | None
    moneyline: TeamMoneylineOut | None
    isNextGame: bool
    live: TeamGameLiveOut | None = None
    edge: TeamGameEdgeOut | None = None

class TeamRosteredPlayer(BaseModel):
    """Output model for a player on a team's roster"""
    id: int
    headshot: str
    first_name: str
    current_team_tri_code: str
    position: str
    last_name: str
    number: int | None
    shoots_catches: str

class TeamSearchResultOut(BaseModel):
    """Output model for a team search result"""
    name: str
    tricode: str
    logoUrl: str | None

class TeamSidePrediction(BaseModel):
    """Prediction details for one side (home or away) of a game"""
    tri_code: str
    prob_win: float | None = None

class TeamGamePredictionOut(BaseModel):
    """Output model for game-level predictions (both teams)"""
    home: TeamSidePrediction
    away: TeamSidePrediction

class TeamMoneylineOut(BaseModel):
    """Output model for a game's moneyline (both teams): the median price of PropLine's consensus books, with the
    best price per side among those books. NHL's partner feed (one book, no best price) is the fallback."""
    home: int
    away: int
    best_home: int | None = None
    best_home_book: str | None = None
    best_away: int | None = None
    best_away_book: str | None = None
    n_books: int | None = None
    source: str = "propline"