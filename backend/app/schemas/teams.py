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
    best price per side among those books. NHL's partner feed (one book, no best price) is the fallback. A game that
    has started shows ESPN's pregame close instead (source "espn", no best price)."""
    home: int
    away: int
    best_home: int | None = None
    best_home_book: str | None = None
    best_away: int | None = None
    best_away_book: str | None = None
    n_books: int | None = None
    source: str = "propline"

class LineupPlayerOut(BaseModel):
    """A player as the lineup endpoint shows him. `slot`: LW / C / RW, LD / RD, F / D (special teams), G."""
    id: int
    firstName: str | None = None
    lastName: str | None = None
    number: int | None = None
    position: str | None = None
    shoots: str | None = None
    headshot: str | None = None
    slot: str | None = None
    injuryStatus: str | None = None   # day_to_day players can be in the lineup; out / ir / ltir / suspended can't
    gamesScratched: int | None = None  # players coming into the lineup: straight games scratched before it

class LineupUnitOut(BaseModel):
    """A projected line (F1-F4), defense pair (D1-D3), power-play (PP1-PP2) or penalty-kill (PK1-PK2) unit."""
    name: str
    players: list[LineupPlayerOut]
    secondsLastGame: int          # seconds this exact group played together last game (5 on 5 for lines and pairs)
    gamesTogether: int            # of the games the projection weighs, how many it played together (a minute or more)

class LineupGoalieOut(BaseModel):
    role: str                     # starter / backup
    status: str                   # confirmed / probable (ESPN) / actual (NHL, once the game has started) / projected
    player: LineupPlayerOut

class LineupGameOut(BaseModel):
    id: int
    startTime: datetime.datetime
    venue: str | None = None
    opponent: str
    home: bool
    gameState: str

class LineupChangesOut(BaseModel):
    """Who is in and out against the team's last lineup."""
    playersIn: list[LineupPlayerOut]
    playersOut: list[LineupPlayerOut]

class TeamInjuryOut(BaseModel):
    """One player on ESPN's injury report (playerId None when he couldn't be matched to an NHL id)."""
    playerId: int | None
    name: str | None
    position: str | None
    status: str                   # out / ir / ltir / suspended / day_to_day
    injuryType: str | None
    returnDate: datetime.date | None
    comment: str | None
    reportedAt: datetime.datetime | None
    player: LineupPlayerOut | None = None

class TeamScratchOut(BaseModel):
    """A player the NHL listed as scratched. healthy: not on the injury report."""
    player: LineupPlayerOut
    healthy: bool
    gamesScratched: int           # consecutive games scratched, up to the one in gameId
    gameId: int

class TeamLineupOut(BaseModel):
    """The roster page's lineup: the next game's lines (posted by the NHL shortly before puck drop, else projected
    from the shift charts of recent games), goalies, injuries and scratches."""
    team: str
    game: LineupGameOut | None
    status: str                   # confirmed (the NHL posted the lineup) / projected
    basedOn: list[int]            # game ids the lines were projected from, newest first
    forwards: list[LineupUnitOut]
    defense: list[LineupUnitOut]
    powerPlay: list[LineupUnitOut]
    penaltyKill: list[LineupUnitOut]
    goalies: list[LineupGoalieOut]
    extras: list[LineupPlayerOut]
    changes: LineupChangesOut
    injuries: list[TeamInjuryOut]
    scratches: list[TeamScratchOut]
    injuryReportAsOf: datetime.datetime | None
    lineupsUpdatedAt: datetime.datetime | None
