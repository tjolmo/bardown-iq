from external.nhl.response_models import GameResponse
from external.nhl.response_models import GameOdds
import httpx

async def fetch_and_get_players_in_a_game(game_id: int) -> list[int] | None:
    """Scrapes player data for a game from API, cleans, returns list of player IDs."""
    base_url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"
    ids = []
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(base_url)
            response.raise_for_status()
            data = response.json().get("playerByGameStats")
            if data and len(data) > 0:
                for team in ["homeTeam", "awayTeam"]:
                    forwards = data.get(team, {}).get("forwards", [])
                    defensemen = data.get(team, {}).get("defense", [])
                    goalies = data.get(team, {}).get("goalies", [])
                    all_players = forwards + defensemen + goalies
                    ids.extend([player.get("playerId") for player in all_players if player.get("playerId") is not None])
                return ids
            return None
        except Exception as e:
            print(f"Error scraping ID {game_id}: {e}")
            return None

async def get_odds_for_current_games() -> list[GameOdds]:
    base_url = "https://api-web.nhle.com/v1/partner-game/US/now"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(base_url)
            response.raise_for_status()
            data = response.json()
            games = data.get("games")
            if not games or len(games) == 0:
                return None
        except Exception as e:
            print(f"Error scraping odds: {e}")
            return None

        return_odds = []
        for game in games:
            game_id = game.get("gameId")
            home_odds = game.get("homeTeam").get("odds")
            away_odds = game.get("awayTeam").get("odds")
            if home_odds and away_odds:
                for odds in home_odds:
                    if odds.get("description") == "MONEY_LINE_2_WAY_TNB":
                        home_moneyline = odds.get("value")
                        break
                for odds in away_odds:
                    if odds.get("description") == "MONEY_LINE_2_WAY_TNB":
                        away_moneyline = odds.get("value")
                        break
            if home_moneyline and away_moneyline:
                return_odds.append(GameOdds(game_id=game_id, home_moneyline=home_moneyline, away_moneyline=away_moneyline))
        return return_odds

# regular season (2) and playoffs (3); the schedule scraper already drops preseason (1)
SCORE_GAME_TYPES = (2, 3)

async def get_current_scores(valid_tri_codes: set[str] | None = None) -> list[GameResponse] | None:
    """Fetches today's games and scores. Games are validated one by one so a single bad
    game is skipped instead of failing the batch. Non regular-season/playoff games are dropped,
    and so are games whose teams are not in valid_tri_codes (when given), since they would
    violate the games -> teams foreign key."""
    base_url = "https://api-web.nhle.com/v1/score/now"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(base_url, follow_redirects=True)
            response.raise_for_status()
            data = response.json()
            games = data.get("games")
            if not games or len(games) == 0:
                return None
        except Exception as e:
            print(f"Error scraping scores: {e}")
            return None

    parsed = []
    for game in games:
        if game.get("gameType") not in SCORE_GAME_TYPES:
            continue
        try:
            parsed_game = GameResponse(**game)
        except Exception as e:
            print(f"Skipping game {game.get('id')} in scores, failed validation: {e}")
            continue
        if valid_tri_codes is not None and (
            parsed_game.home_team_tri_code not in valid_tri_codes
            or parsed_game.away_team_tri_code not in valid_tri_codes
        ):
            print(f"Skipping game {parsed_game.id} in scores, team not in DB: "
                  f"{parsed_game.away_team_tri_code} @ {parsed_game.home_team_tri_code}")
            continue
        parsed.append(parsed_game)
    return parsed or None
