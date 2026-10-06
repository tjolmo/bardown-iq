from external.http import get_with_retries
from .response_models import PlayerLandingResponse

async def fetch_and_get_players_info(player_id: int) -> PlayerLandingResponse | None:
    """Scrapes player info"""
    base_url = f"https://api-web.nhle.com/v1/player/{player_id}/landing"
    try:
        response = await get_with_retries(base_url)
        response.raise_for_status()
        return PlayerLandingResponse(**response.json())
    except Exception as e:
        print(f"Error scraping ID {player_id}: {e}")
        return None