"""What the day's game cards show beyond the stored game: the live period/clock of a game under way and the model's
edge against the moneyline."""
import datetime

from external.nhl.response_models import GameLiveStatus
from predictions.prediction_log import devig_pair
from app.schemas.teams import TeamGameEdgeOut, TeamGameLiveOut, TeamMoneylineOut

# ask the score feed about a day's games from shortly before the first puck drop
LIVE_LEAD_TIME = datetime.timedelta(minutes=10)


def needs_live_status(games, now: datetime.datetime | None = None) -> bool:
    """True once any of the games is about to start or has started (the feed is cached, so this costs at most one
    NHL call per LIVE_SCORES_POLL_MINUTES)."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return any(g.start_time is not None and g.start_time <= now + LIVE_LEAD_TIME for g in games)


# NHL game states before puck drop; every other state (LIVE, CRIT, FINAL, OFF) means the game has started
NOT_STARTED_STATES = ("FUT", "PRE")


def has_started(game, status: GameLiveStatus | None = None) -> bool:
    """True once the game is under way or over, by the score feed when it has the game, else the stored state."""
    state = status.game_state if status is not None else game.game_state
    return state not in NOT_STARTED_STATES


def format_clock(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def live_out(status: GameLiveStatus | None) -> TeamGameLiveOut | None:
    if status is None:
        return None
    return TeamGameLiveOut(period=status.period, periodType=status.period_type,
                           secondsRemaining=status.seconds_remaining, timeRemaining=format_clock(status.seconds_remaining),
                           inIntermission=status.in_intermission, clockRunning=status.clock_running, asOf=status.as_of)


def game_edge(home_tri_code: str, away_tri_code: str, prob_home: float | None, prob_away: float | None,
              moneyline: TeamMoneylineOut | None) -> TeamGameEdgeOut | None:
    """The side whose model win probability sits furthest above the no-vig moneyline probability, in points. With two
    sides summing to one, one side's edge is the other's deficit, so this is the side the model likes."""
    if prob_home is None or prob_away is None or moneyline is None:
        return None
    market_home = devig_pair(moneyline.home, moneyline.away)
    if market_home is None:
        return None
    home_points = (prob_home - market_home) * 100
    away_points = (prob_away - (1 - market_home)) * 100
    if home_points >= away_points:
        return TeamGameEdgeOut(tri_code=home_tri_code, side="home", points=round(home_points, 1))
    return TeamGameEdgeOut(tri_code=away_tri_code, side="away", points=round(away_points, 1))
