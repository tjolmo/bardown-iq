from external.odds_api.response_models import PlayerPropsResponse
from datetime import datetime
from external.odds_api.response_models import EventResponse
import logging
import os
import httpx
from pydantic import ValidationError

logger = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4/sports/icehockey_nhl"
REQUEST_TIMEOUT_SECONDS = 30


async def _get_json(client: httpx.AsyncClient, url: str, params: dict):
    """GETs an Odds API endpoint. Returns the parsed JSON, or None on any failure (logged)."""
    try:
        response = await client.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    except httpx.HTTPError as e:
        logger.error("Odds API request failed: %s", e)
        return None
    logger.info(
        "Odds API %s -> %s (credits remaining: %s, used: %s)",
        response.request.url.path, response.status_code,
        response.headers.get("x-requests-remaining"), response.headers.get("x-requests-used"),
    )
    if response.status_code != 200:
        # 401 = bad/missing key, 422 = bad params, 429 = quota or rate limit
        logger.error("Odds API returned %s: %s", response.status_code, response.text[:200])
        return None
    try:
        return response.json()
    except ValueError:
        logger.error("Odds API returned a non-JSON body")
        return None


async def get_upcoming_games_odds_api(start_time: datetime, end_time: datetime) -> list[EventResponse]:
    """Gets event ids for upcoming games, used for props later"""
    if not os.getenv("ODDS_API_KEY"):
        logger.error("ODDS_API_KEY is not set, skipping Odds API events request")
        return []
    async with httpx.AsyncClient() as client:
        params = {
            "apiKey": os.getenv("ODDS_API_KEY"),
            "commenceTimeFrom": start_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "commenceTimeTo": end_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        }
        events = await _get_json(client, f"{BASE_URL}/events", params)
    if not isinstance(events, list):
        if events is not None:
            logger.error("Unexpected Odds API events payload: %s", str(events)[:200])
        return []
    return parse_events(events)


def parse_events(events: list) -> list[EventResponse]:
    """Validates events one by one so a single malformed event does not drop the rest."""
    parsed = []
    for event in events:
        try:
            parsed.append(EventResponse(**event))
        except (ValidationError, TypeError) as e:
            logger.warning("Skipping malformed Odds API event: %s", e)
    return parsed


async def get_player_props(event_id: str) -> list[PlayerPropsResponse]:
    """Gets player props for a specific event_id"""
    if not os.getenv("ODDS_API_KEY"):
        logger.error("ODDS_API_KEY is not set, skipping Odds API props request")
        return []
    async with httpx.AsyncClient() as client:
        params = {
            "apiKey": os.getenv("ODDS_API_KEY"),
            "regions": "us",
            # blocked shots and shots on goal added: blocks are the market where the model beat the prices. Each market
            # returned costs one credit per event (x regions). There is no NHL hits market (not in the docs' market
            # list, and no US book listed one on /events/{id}/markets in Oct 2026): hits come from ESPN only.
            "markets": "player_points,player_assists,player_goals,player_total_saves,player_blocked_shots,player_shots_on_goal",
            "oddsFormat": "american"
        }
        results = await _get_json(client, f"{BASE_URL}/events/{event_id}/odds", params)
    if not isinstance(results, dict):
        if results is not None:
            logger.error("Unexpected Odds API props payload for event %s: %s", event_id, str(results)[:200])
        return []
    return parse_player_props(results)


def parse_player_props(results: dict) -> list[PlayerPropsResponse]:
    """Flattens an event odds payload into props, skipping outcomes that are incomplete."""
    return_list = []
    for bookmaker in results.get("bookmakers", []):
        book_key = bookmaker.get("key") or bookmaker.get("title")
        for market in bookmaker.get("markets", []):
            prop_type = market.get("key")
            book_last_update = market.get("last_update") or bookmaker.get("last_update")
            for outcome in market.get("outcomes", []):
                name = outcome.get("description")
                split_name = name.split(' ') if isinstance(name, str) else []
                if len(split_name) >= 2:
                    first_name = split_name[0]
                    last_name = ' '.join(split_name[1:])
                else:
                    continue
                try:
                    return_list.append(PlayerPropsResponse(
                        prop_type=prop_type,
                        first_name=first_name,
                        last_name=last_name,
                        line=outcome["point"] if outcome.get("point") is not None else 0.5,  # yes/no markets have no point
                        odds=outcome.get("price"),
                        over_under=outcome.get("name"),
                        bookmaker=book_key,
                        book_last_update=book_last_update,
                    ))
                except ValidationError as e:
                    logger.warning("Skipping malformed Odds API outcome for %s: %s", name, e)
    return return_list
