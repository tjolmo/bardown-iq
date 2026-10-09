import io
import logging
import pandas as pd
import requests
from .player import _normalize_tricodes

logger = logging.getLogger(__name__)

# every team game since 2008-09 in one file (~120 MB), so it's downloaded once and filtered to the seasons wanted
ALL_TEAMS_URL = "https://moneypuck.com/moneypuck/playerData/careers/gameByGame/all_teams.csv"
DOWNLOAD_TIMEOUT = (10, 300)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}

KEYS = ["gameId", "playerTeam", "opposingTeam", "season", "gameDate", "home_or_away", "playoffGame"]
# MoneyPuck column -> team_game_stats column, per situation
SITUATION_COLUMNS = {
    "all": {"goalsFor": "goals_for", "goalsAgainst": "goals_against", "xGoalsFor": "x_goals_for",
            "xGoalsAgainst": "x_goals_against", "shotAttemptsFor": "shot_attempts_for",
            "shotAttemptsAgainst": "shot_attempts_against"},
    "5on5": {"flurryScoreVenueAdjustedxGoalsFor": "x_goals_for_5v5", "flurryScoreVenueAdjustedxGoalsAgainst": "x_goals_against_5v5",
             "scoreAdjustedShotsAttemptsFor": "shot_attempts_for_5v5", "scoreAdjustedShotsAttemptsAgainst": "shot_attempts_against_5v5",
             "goalsFor": "goals_for_5v5", "goalsAgainst": "goals_against_5v5"},
    "5on4": {"xGoalsFor": "pp_x_goals_for", "iceTime": "pp_toi"},
    "4on5": {"xGoalsAgainst": "pk_x_goals_against", "iceTime": "pk_toi"},
}

def parse_team_game_stats(raw: pd.DataFrame, seasons: list[int] | None = None) -> list[dict]:
    """One wide row per (game, team) with the all-situation, 5v5, power-play and penalty-kill columns."""
    if seasons is not None:
        raw = raw[raw["season"].isin(seasons)]
    raw = _normalize_tricodes(raw.copy())
    wide = None
    for situation, cols in SITUATION_COLUMNS.items():
        part = raw.loc[raw["situation"] == situation, KEYS + list(cols)].rename(columns=cols)
        wide = part if wide is None else wide.merge(part, on=KEYS, how="left")
    if wide is None or wide.empty:
        return []
    wide = wide.rename(columns={"gameId": "game_id", "playerTeam": "team_tri_code", "opposingTeam": "opposing_team_tri_code",
                                "gameDate": "game_date", "home_or_away": "home_away", "playoffGame": "playoff"})
    wide["playoff"] = wide["playoff"].astype(bool)
    wide = wide.drop_duplicates(["game_id", "team_tri_code"])
    # NaN (a situation that never happened in a game) -> None for the DB
    return [{k: (None if pd.isna(v) else v) for k, v in row.items()} for row in wide.to_dict("records")]

def scrape_team_game_stats(seasons: list[int] | None = None) -> list[dict] | None:
    """Downloads MoneyPuck's team game-by-game file; `seasons` are start years (None = every season)."""
    try:
        response = requests.get(ALL_TEAMS_URL, headers=HEADERS, timeout=DOWNLOAD_TIMEOUT)
        response.raise_for_status()
        usecols = set(KEYS) | {"situation"} | {c for cols in SITUATION_COLUMNS.values() for c in cols}
        raw = pd.read_csv(io.BytesIO(response.content), usecols=lambda c: c in usecols)
        return parse_team_game_stats(raw, seasons)
    except Exception as e:
        logger.error("Failed to load MoneyPuck team game stats from %s: %s", ALL_TEAMS_URL, e)
        return None
