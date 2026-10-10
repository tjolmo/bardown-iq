import datetime

from pydantic import BaseModel

class PlayerGameLogGetOut(BaseModel):
    """Output model for a Skater's game log"""
    game_id: int
    player_id: int
    season: int
    name: str
    home_away: str
    player_team_tricode: str
    opposing_team_tricode: str
    game_date: int
    goals: int
    primary_assists: int
    secondary_assists: int
    points: int
    x_goals: float
    toi: float
    high_danger_shots: int
    shot_attempts: int
    on_ice_x_goals_percentage: float
    game_score: float

    class Config:
        from_attributes = True

class GoalieGameLogGetOut(BaseModel):
    """Output model for a Goalie's game log"""
    game_id: int
    player_id: int
    season: int
    name: str
    home_away: str
    player_team_tricode: str
    opposing_team_tricode: str
    game_date: int
    toi: float
    x_goals_against: float
    goals_against: int
    unblocked_shot_attempts: int
    x_rebounds: float
    rebounds: int
    x_freeze: float
    freeze: int
    x_sog: float
    sog: int
    x_play_stopped: float
    play_stopped: int
    x_play_continued_in_zone: float
    x_play_continued_outside_zone: float
    flurry_adjusted_x_goals: float
    low_danger_shots: int
    medium_danger_shots: int
    high_danger_shots: int
    low_danger_x_goals: float
    medium_danger_x_goals: float
    high_danger_x_goals: float
    blocked_shot_attempts: int
    penality_minutes: int
    penalties: int

    class Config:
        from_attributes = True

class SkaterSeasonBasicStatsGetOut(BaseModel):
    """Output model for a Skater's season basic stats"""
    games: int
    goals: int
    assists: int
    points: int

class SkaterLast5BasicStatsGetOut(BaseModel):
    """Output model for a Skater's last 5 games basic stats"""
    date: str | None
    opposing_team_tricode: str
    goals: int
    assists: int
    points: int
    home_away: str

class PlayerBasicInfoOut(BaseModel):
    """Output model for a player's basic info"""
    name: str
    number: int | None
    position: str
    team: str
    headshotUrl: str

class PlayerNextGameGetOut(BaseModel):
    """Output model for a player's upcoming game info"""
    date: str | None
    opposing_team_tricode: str
    venue: str
    time: datetime.datetime
    home_away: str

class GoalieLast5BasicStatsGetOut(BaseModel):
    """Output model for a Goalie's last 5 games basic stats"""
    date: str | None
    opposing_team_tricode: str
    saves: int
    goals_against: int
    save_percentage: float
    home_away: str

class SkaterGameOut(BaseModel):
    """One game of a skater's log for the player page: box score, shot quality, and what the model expected"""
    game_id: int
    date: str                   # ISO date of the game
    opposing_team_tricode: str
    home_away: str | None
    toi: float                  # seconds
    goals: int
    primary_assists: int
    secondary_assists: int
    assists: int
    points: int
    # null on rows scraped before these columns existed
    shots_on_goal: int | None
    hits: int | None
    blocked_shots: int | None
    pp_points: int | None
    pp_toi: float | None        # 5on4 seconds
    x_goals: float
    shot_attempts: int
    high_danger_shots: int
    on_ice_x_goals_percentage: float
    game_score: float
    # model stat -> the expected count the forward test logged before puck drop (empty when never logged)
    expected: dict[str, float] = {}

class GoalieGameOut(BaseModel):
    """One game of a goalie's log for the player page"""
    game_id: int
    date: str                   # ISO date of the game
    opposing_team_tricode: str
    home_away: str | None
    toi: float                  # seconds
    shots_against: int          # shots on goal faced, goals included
    saves: int
    goals_against: int
    x_goals_against: float
    high_danger_shots: int
    high_danger_x_goals: float
    rebounds: int
    x_rebounds: float
    # model stat (goals_against, sog, saves) -> expected count logged before puck drop
    expected: dict[str, float] = {}

class GoalieSeasonBasicStatsGetOut(BaseModel):
    """Output model for a Goalie's season basic stats"""
    games: int
    gaa: float
    save_percentage: float

class PlayerSearchResultOut(BaseModel):
    """Output model for a player search result"""
    id: int
    first_name: str
    last_name: str
    headshot: str | None
    current_team_tri_code: str | None
    position: str | None

    class Config:
        from_attributes = True

class PlayerPredictionOut(BaseModel):
    """Output model for a player's prediction"""
    goals: float
    assists: float
    points: float
    prob_goal: float | None = None
    prob_assist: float | None = None
    prob_point: float | None = None
    shots_on_goal: float | None = None
    blocked_shots: float | None = None
    hits: float | None = None
    pp_points: float | None = None

    class Config:
        from_attributes = True

class GoaliePredictionOut(BaseModel):
    """Output model for a goalie's prediction"""
    goals_against: float
    saves: float
    save_percentage: float | None = None
    shots_against: float | None = None
    # the numbers above assume he starts; whether he is his team's expected starter, and how sure that is
    # ("confirmed", "probable" or "projected"; None when unknown)
    starting: bool | None = None
    starter_status: str | None = None

    class Config:
        from_attributes = True
    
class PropBookPriceOut(BaseModel):
    """One book's price for a prop side (the "+N books" list under a prop card)"""
    book: str
    odds: float
    line: float
    # one of the books the shown best price and the consensus come from (books.CONSENSUS_BOOKS)
    consensus: bool = True

class PlayerPropOut(BaseModel):
    """Output model for a player's prop"""
    game_id: int
    player_id: int
    prop_type: str
    over_under: str
    odds: float
    line: float
    # the model's chance this side wins, and its expected return per unit at these odds (None if no model yet)
    model_prob: float | None = None
    edge: float | None = None
    # where the price came from: "propline" (best price across the consensus books at the consensus line; `book`
    # is the book with that price) or "espn" (one book's market from ESPN's feed, e.g. hits, which PropLine has no
    # market for)
    source: str = "propline"
    book: str | None = None
    # every other stored book's price for this side (PropLine rows only)
    other_books: list[PropBookPriceOut] = []
class EdgePlayerOut(BaseModel):
    """A player on the "players with edge" board: at least one prop side with a positive edge"""
    player_id: int
    first_name: str
    last_name: str
    headshot: str | None = None
    position: str | None = None
    team: str | None = None
    opponent: str
    home: bool
    game_id: int
    start_time: str | None = None
    # goalies: how sure the starter pick is (confirmed / probable / projected); saves props assume he starts
    starter_status: str | None = None
    best_edge: float
    # every priced prop of the player's game, best edge first
    props: list[PlayerPropOut]

class EdgeBoardOut(BaseModel):
    """The next slate's players with edge"""
    game_date: int | None
    built_at: str
    # players whose props could be priced (the denominator of the board)
    players_priced: int
    # a background rebuild was started because this copy is stale
    refreshing: bool = False
    players: list[EdgePlayerOut]
