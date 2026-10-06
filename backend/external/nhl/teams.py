from external.http import get_with_retries
from .response_models import TeamResponse, PlayerResponse, TeamHistoryResponse, GameResponse

async def fetch_and_clean_team(team_id: int) -> tuple[TeamResponse, TeamHistoryResponse] | None:
    """Scrapes team data from API, cleans, returns"""
    base_url = f"https://api.nhle.com/stats/rest/en/team/id/{team_id}"
    try:
        response = await get_with_retries(base_url)
        response.raise_for_status()
        data = response.json().get("data")
        if data and len(data) > 0:
            return (TeamResponse(**data[0]), TeamHistoryResponse(**data[0]))
        return None
    except Exception as e:
        print(f"Error scraping ID {team_id}: {e}")
        return None

async def fetch_and_clean_team_roster(team_tricode: str, season: str="current") -> list[PlayerResponse] | None:
    """Scrapes team roster data from API, cleans, returns list of PlayerResponse."""
    base_url = f"https://api-web.nhle.com/v1/roster/{team_tricode}/{season}"
    try:
        response = await get_with_retries(base_url)
        response.raise_for_status()
        # get forwards, defensemen, goalies
        forwards = response.json().get("forwards", [])
        defensemen = response.json().get("defensemen", [])
        goalies = response.json().get("goalies", [])
        all_players = forwards + defensemen + goalies
        if all_players and len(all_players) > 0:
            return [PlayerResponse(**player) for player in all_players]
        return None
    except Exception as e:
        print(f"Error scraping Team {team_tricode} Season {season} Roster: {e}")
        return None

async def fetch_and_clean_team_schedule(team_tricode: str, season: str="now") -> list[GameResponse] | None:
    """Scrapes team schedule data from API, cleans, returns list of GameResponse."""
    """Default is current season, but can also pass in a specific season in format '20222023'."""
    base_url = f"https://api-web.nhle.com/v1/club-schedule-season/{team_tricode}/{season}"
    try:
        response = await get_with_retries(base_url)
        response.raise_for_status()
        # get games
        games = response.json().get("games", [])
        #remove all preseason games
        games = [game for game in games if game.get("gameType") != 1]
        if games and len(games) > 0:
            return [GameResponse(**game) for game in games]
        return None
    except Exception as e:
        print(f"Error scraping Team {team_tricode} Season {season} Schedule: {e}")
        return None
