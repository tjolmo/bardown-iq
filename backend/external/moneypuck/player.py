import pandas as pd
from .response_models import SkaterGameLogResponse, GoalieGameLogResponse
import zipfile
import io
import logging
import requests

logger = logging.getLogger(__name__)

# (connect, read) seconds; the season zips are a few MB so reads can be slow but not unbounded
DOWNLOAD_TIMEOUT = (10, 120)

TRICODE_MAP = {
    "T.B": "TBL",
    "S.J": "SJS",
    "N.J": "NJD",
    "L.A": "LAK",
}

def _download_season_zip(url: str) -> io.BytesIO:
    """Downloads a season zip, raising on timeouts and non-2xx responses (so an HTML error page is never treated as a zip)."""
    response = requests.get(url, timeout=DOWNLOAD_TIMEOUT)
    response.raise_for_status()
    return io.BytesIO(response.content)

def _validate_rows(model, rows: list[dict], label: str) -> list:
    """Validates each CSV row on its own so one malformed row is skipped (and counted) instead of discarding the season."""
    valid = []
    skipped = 0
    first_error = None
    for row in rows:
        try:
            valid.append(model.model_validate(row))
        except Exception as e:
            skipped += 1
            if first_error is None:
                first_error = e
    if skipped:
        logger.warning("Skipped %d of %d %s rows that failed validation; first error: %s", skipped, len(rows), label, first_error)
    return valid

# fixes issue with older gamelogs now being scraped
def _normalize_tricodes(df: pd.DataFrame) -> pd.DataFrame:
    """Replace MoneyPuck dot-separated team codes with standard 3-letter tricodes."""
    for col in ("playerTeam", "opposingTeam"):
        if col in df.columns:
            df[col] = df[col].replace(TRICODE_MAP)
    return df

def scrape_skater_game_data(player_id: int, start_date: int|None = None) -> list[SkaterGameLogResponse] | None:
    """REMOVE LATER"""
    """Scrapes game log data for a skater from Moneypuck, cleans, returns list of SkaterGameLogResponse."""
    csv_url = f"https://moneypuck.com/moneypuck/playerData/careers/gameByGame/regular/skaters/{player_id}.csv"
    cols= [
        'playerId', 'season', 'name', 'gameId', 'home_or_away',
        'playerTeam', 'opposingTeam', 'gameDate', 'situation',
        'I_F_goals', 'I_F_primaryAssists', 'I_F_secondaryAssists', 'I_F_points',
        'I_F_xGoals', 'icetime', 'I_F_highDangerShots', 
        'I_F_shotAttempts', 'onIce_xGoalsPercentage', 'gameScore'
    ]

    # stop 403 error
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        df = pd.read_csv(
            csv_url, 
            usecols=cols, 
            storage_options=headers
        )
        # filters to last 5 seasons. All situations, meaning all game
        filtered = df.query('season >= 2020 and situation == "all"').copy()
        if start_date:
            filtered = filtered.query(f'gameDate >= {start_date}').copy()
        filtered = _normalize_tricodes(filtered)
        # convert to list of SkaterGameLogResponse
        return [SkaterGameLogResponse.model_validate(row) for row in filtered.to_dict("records")]
    except Exception as e:
        print(f"Error loading data: {e}")
        return None

def scrape_goalie_game_data(player_id: int, start_date: int|None = None) -> list[GoalieGameLogResponse] | None:
    """REMOVE LATER"""
    """Scrapes game log data for a goalie from Moneypuck, cleans, returns list of GoalieGameLogResponse."""
    csv_url = f"https://moneypuck.com/moneypuck/playerData/careers/gameByGame/regular/goalies/{player_id}.csv"
    cols= [
        'playerId', 'season', 'name', 'gameId', 'home_or_away',
        'playerTeam', 'opposingTeam', 'gameDate',
        "situation", "icetime", "xGoals", "goals",
        "unblocked_shot_attempts", "xRebounds", "rebounds",
        "xFreeze", "freeze", "xOnGoal", "ongoal", "xPlayStopped",
        "playStopped", "xPlayContinuedInZone", "xPlayContinuedOutsideZone", "flurryAdjustedxGoals",
        "lowDangerShots", "mediumDangerShots", "highDangerShots", "lowDangerxGoals",
        "mediumDangerxGoals", "highDangerxGoals", "blocked_shot_attempts",
        "penalityMinutes", "penalties"
    ]

    # stop 403 error
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        df = pd.read_csv(
            csv_url, 
            usecols=cols, 
            storage_options=headers
        )
        # filters to last 5 seasons. All situations, meaning all game
        filtered = df.query('season >= 2020 and situation == "all"').copy()
        # filter by date
        if start_date:
            filtered = filtered.query(f'gameDate >= {start_date}').copy()
        filtered = _normalize_tricodes(filtered)
        # convert to list of GoalieGameLogResponse
        return [GoalieGameLogResponse.model_validate(row) for row in filtered.to_dict("records")]
    except Exception as e:
        print(f"Error loading data: {e}")
        return None

def scrape_all_skater_game_logs(season: int) -> list[SkaterGameLogResponse] | None:
    """Scrapes game log data for all skaters for one season from Moneypuck, cleans, returns list of SkaterGameLogResponse."""
    csv_url = f"https://peter-tanner.com/moneypuck/downloads/seasonPlayersSummary/skaters/{season}.zip"
    cols = [
        'playerId', 'season', 'name', 'gameId', 'home_or_away',
        'playerTeam', 'opposingTeam', 'gameDate', 'situation',
        'I_F_goals', 'I_F_primaryAssists', 'I_F_secondaryAssists', 'I_F_points',
        'I_F_xGoals', 'icetime', 'I_F_highDangerShots', 
        'I_F_shotAttempts', 'onIce_xGoalsPercentage', 'gameScore'
    ]
    # download the zip file and unpack the csv
    try:
        csv_data = _download_season_zip(csv_url)
        with zipfile.ZipFile(csv_data) as z:
            with z.open(f"{season}.csv") as f:
                df = pd.read_csv(f, usecols=cols)
                filtered = df.query('situation == "all"').copy()
                filtered = _normalize_tricodes(filtered)
            return _validate_rows(SkaterGameLogResponse, filtered.to_dict("records"), f"skater {season}")
    except Exception as e:
        logger.error("Failed to load MoneyPuck %s data for season %s from %s: %s", "skater", season, csv_url, e)
        return None

def scrape_all_goalie_game_logs(season: int) -> list[GoalieGameLogResponse] | None:
    """Scrapes game log data for all goalies for one season from Moneypuck, cleans, returns list of GoalieGameLogResponse."""
    csv_url = f"https://peter-tanner.com/moneypuck/downloads/seasonPlayersSummary/goalies/{season}.zip"
    cols= [
        'playerId', 'season', 'name', 'gameId', 'home_or_away',
        'playerTeam', 'opposingTeam', 'gameDate',
        "situation", "icetime", "xGoals", "goals",
        "unblocked_shot_attempts", "xRebounds", "rebounds",
        "xFreeze", "freeze", "xOnGoal", "ongoal", "xPlayStopped",
        "playStopped", "xPlayContinuedInZone", "xPlayContinuedOutsideZone", "flurryAdjustedxGoals",
        "lowDangerShots", "mediumDangerShots", "highDangerShots", "lowDangerxGoals",
        "mediumDangerxGoals", "highDangerxGoals", "blocked_shot_attempts",
        "penalityMinutes", "penalties"
    ]
    # download the zip file and unpack the csv
    try:
        csv_data = _download_season_zip(csv_url)
        with zipfile.ZipFile(csv_data) as z:
            with z.open(f"{season}.csv") as f:
                df = pd.read_csv(f, usecols=cols)
                filtered = df.query('situation == "all"').copy()
                filtered = _normalize_tricodes(filtered)
            return _validate_rows(GoalieGameLogResponse, filtered.to_dict("records"), f"goalie {season}")
    except Exception as e:
        logger.error("Failed to load MoneyPuck %s data for season %s from %s: %s", "goalie", season, csv_url, e)
        return None