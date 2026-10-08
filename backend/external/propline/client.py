"""PropLine (api.prop-line.com) client: NHL events, every book's player prop prices and game lines.

PropLine serves the Odds API's response shape (bookmakers -> markets -> outcomes, American prices), so the parsed
output is the same as the old Odds API client's; its market keys are mapped onto the app's in books.py.
The free tier allows 1,000 requests a day (resets 00:00 UTC); each request counts once whatever the markets.
"""
from datetime import datetime
import logging
import os
import re

import httpx
from pydantic import ValidationError

from app.name_matching import normalize_name

from external.propline.books import (BOOKMAKERS, GAME_MARKETS, MILESTONE_MARKETS, PROP_MARKETS, RUNG_MARKETS,
                                     app_prop_key)
from external.propline.response_models import EventResponse, GameLineResponse, PlayerPropsResponse

logger = logging.getLogger(__name__)

BASE_URL = "https://api.prop-line.com/v1/sports/hockey_nhl"
REQUEST_TIMEOUT_SECONDS = 30
WANTED_PROP_MARKETS = set(PROP_MARKETS) | set(MILESTONE_MARKETS)
# requested when an event's market list can't be read: the four NHL prop markets PropLine documents
DOCUMENTED_PROP_MARKETS = ("player_goals", "player_shots_on_goal", "goalie_saves", "player_blocked_shots")


def _api_key() -> str | None:
    return os.getenv("PROPLINE_API_KEY")


async def _get_json(client: httpx.AsyncClient, url: str, params: dict | None = None):
    """GETs a PropLine endpoint. Returns the parsed JSON, or None on any failure (logged)."""
    try:
        response = await client.get(url, params=params or {}, headers={"X-API-Key": _api_key() or ""},
                                    timeout=REQUEST_TIMEOUT_SECONDS)
    except httpx.HTTPError as e:
        logger.error("PropLine request failed: %s", e)
        return None
    logger.info(
        "PropLine %s -> %s (requests remaining today: %s, used: %s)",
        response.request.url.path, response.status_code,
        response.headers.get("x-daily-remaining"), response.headers.get("x-daily-used"),
    )
    if response.status_code != 200:
        # 401 = bad/missing key, 403 = paid-tier endpoint, 404 = unknown sport/event, 429 = daily quota
        logger.error("PropLine returned %s: %s", response.status_code, response.text[:300])
        return None
    try:
        return response.json()
    except ValueError:
        logger.error("PropLine returned a non-JSON body")
        return None


TEAM_SUFFIX = re.compile(r"\s*\([A-Z]{2,3}\)\s*$")     # Bovada: "Mackenzie Blackwood (COL)"
RUNG = re.compile(r"^(\d+)\+")                         # milestone outcome names: "1+ Assists", "22+ Saves"


def _split_name(name) -> tuple[str, str] | None:
    name = TEAM_SUFFIX.sub("", name) if isinstance(name, str) else name
    split_name = name.split(' ') if isinstance(name, str) else []
    if len(split_name) < 2:
        return None
    return split_name[0], ' '.join(split_name[1:])


def _nhl_id(player_id) -> int | None:
    """'nhl:8479318' -> 8479318; anything else (another league's id, None) -> None."""
    if isinstance(player_id, str) and player_id.startswith("nhl:"):
        try:
            return int(player_id[4:])
        except ValueError:
            return None
    return None


async def get_upcoming_games(start_time: datetime, end_time: datetime) -> list[EventResponse]:
    """Upcoming NHL events starting between start_time and end_time (PropLine's events endpoint takes no window)."""
    if not _api_key():
        logger.error("PROPLINE_API_KEY is not set, skipping PropLine events request")
        return []
    async with httpx.AsyncClient() as client:
        events = await _get_json(client, f"{BASE_URL}/events")
    if not isinstance(events, list):
        if events is not None:
            logger.error("Unexpected PropLine events payload: %s", str(events)[:200])
        return []
    return [e for e in parse_events(events) if start_time <= e.commence_time <= end_time]


def parse_events(events: list) -> list[EventResponse]:
    """Validates events one by one so a single malformed event does not drop the rest."""
    parsed = []
    for event in events:
        try:
            parsed.append(EventResponse(**event))
        except (ValidationError, TypeError) as e:
            logger.warning("Skipping malformed PropLine event: %s", e)
    return parsed


def _market_keys(payload) -> set[str]:
    """Every market key named anywhere in an event's /markets payload (its exact shape isn't pinned down: a list
    of keys, of {"key": ...} objects, or a dict wrapping either)."""
    found = set()
    if isinstance(payload, str):
        found.add(payload)
    elif isinstance(payload, list):
        for item in payload:
            found |= _market_keys(item)
    elif isinstance(payload, dict):
        for k, v in payload.items():
            if k in ("key", "market", "market_key") and isinstance(v, str):
                found.add(v)
            elif isinstance(v, (list, dict)):
                found |= _market_keys(v)
            elif isinstance(k, str) and k in WANTED_PROP_MARKETS:
                found.add(k)    # {market_key: count} maps
    return found


async def event_markets(client: httpx.AsyncClient, event_id: str) -> list[str]:
    """The prop markets to request for an event: the wanted ones the event lists, or PropLine's documented NHL
    markets when the list can't be read (asking for markets an event lacks only returns fewer rows)."""
    payload = await _get_json(client, f"{BASE_URL}/events/{event_id}/markets")
    listed = _market_keys(payload) & WANTED_PROP_MARKETS if payload is not None else set()
    return sorted(listed) if listed else list(DOCUMENTED_PROP_MARKETS)


async def get_event_odds(event_id: str) -> dict | None:
    """One event's player props and game lines from every fetched book, in one odds request (plus one for the
    event's market list). None on failure."""
    if not _api_key():
        logger.error("PROPLINE_API_KEY is not set, skipping PropLine odds request")
        return None
    async with httpx.AsyncClient() as client:
        markets = await event_markets(client, event_id)
        params = {"markets": ",".join(list(GAME_MARKETS) + markets), "bookmakers": ",".join(BOOKMAKERS)}
        results = await _get_json(client, f"{BASE_URL}/events/{event_id}/odds", params)
    if not isinstance(results, dict):
        if results is not None:
            logger.error("Unexpected PropLine odds payload for event %s: %s", event_id, str(results)[:200])
        return None
    return results


async def get_player_props(event_id: str) -> list[PlayerPropsResponse]:
    """Player props for one event (same output as the old Odds API client)."""
    results = await get_event_odds(event_id)
    return parse_player_props(results) if results else []


async def get_game_lines() -> list[tuple[EventResponse, list[GameLineResponse]]]:
    """(event, its game lines) for every upcoming game: moneyline, puck line and total from one bulk request."""
    if not _api_key():
        logger.error("PROPLINE_API_KEY is not set, skipping PropLine game lines request")
        return []
    async with httpx.AsyncClient() as client:
        params = {"markets": ",".join(GAME_MARKETS), "bookmakers": ",".join(BOOKMAKERS)}
        events = await _get_json(client, f"{BASE_URL}/odds", params)
    if not isinstance(events, list):
        if events is not None:
            logger.error("Unexpected PropLine bulk odds payload: %s", str(events)[:200])
        return []
    out = []
    for event in events:
        parsed = parse_events([event]) if isinstance(event, dict) else []
        if parsed:
            out.append((parsed[0], parse_game_lines(event)))
    return out


def _live_markets(results: dict):
    """(book key, market) for every market still on the board: pulled (suspended) markets are the last quoted
    legs, not a live price, and a book's frozen pregame quote on a live game (pregame_only) won't move again."""
    for bookmaker in results.get("bookmakers", []) or []:
        book_key = bookmaker.get("key") or bookmaker.get("title")
        if bookmaker.get("pregame_only"):
            continue
        for market in bookmaker.get("markets", []) or []:
            if market.get("suspended_at"):
                continue
            yield book_key, bookmaker, market


def _side(name) -> str | None:
    """Over/Under as the app stores them; one-sided yes/no markets settle like over/under 0.5."""
    side = str(name or "").strip().lower()
    return {"over": "Over", "under": "Under", "yes": "Over", "no": "Under"}.get(side)


def _prop_side(outcome: dict, milestone_key: bool, prop_type: str) -> tuple[str, float] | None:
    """(side, line) of a player prop outcome, or None to skip it. Besides Over/Under and Yes/No, books post
    "1+ Assists" rungs (over 0.5, for markets whose main line is 0.5; higher rungs are alternate lines and skipped)
    and anytime-goalscorer lists whose outcome is named after the player (a yes at 0.5)."""
    name = str(outcome.get("name") or "").strip()
    point = outcome.get("point")
    side = _side(name)
    if side is not None:
        if milestone_key or point is None:
            return (side, 0.5) if prop_type in RUNG_MARKETS else None
        return side, point
    rung = RUNG.match(name)
    if rung:
        return ("Over", 0.5) if int(rung.group(1)) == 1 and prop_type in RUNG_MARKETS else None
    if point is None and name and name == str(outcome.get("description") or "").strip():
        return "Over", 0.5
    return None


def parse_player_props(results: dict) -> list[PlayerPropsResponse]:
    """Flattens an event odds payload into props, skipping outcomes that are incomplete, alternate lines and
    markets the app doesn't use."""
    return_list = []
    for book_key, bookmaker, market in _live_markets(results):
        prop_type, milestone = app_prop_key(market.get("key"))
        if prop_type is None:
            continue
        line_type = market.get("line_type") or "main"
        if line_type == "alternate":
            continue
        book_last_update = market.get("last_update") or bookmaker.get("last_update")
        for outcome in market.get("outcomes", []) or []:
            if (outcome.get("line_type") or line_type) == "alternate" or outcome.get("dfs_odds_type") not in (None, "standard"):
                continue
            name = outcome.get("description")
            split = _split_name(name)
            side_line = _prop_side(outcome, milestone, prop_type)
            if split is None or side_line is None or outcome.get("price") is None:
                continue
            try:
                return_list.append(PlayerPropsResponse(
                    prop_type=prop_type,
                    first_name=split[0],
                    last_name=split[1],
                    line=side_line[1],
                    odds=outcome.get("price"),
                    over_under=side_line[0],
                    bookmaker=book_key,
                    book_last_update=outcome.get("book_updated_at") or book_last_update,
                    nhl_player_id=_nhl_id(outcome.get("player_id")),
                ))
            except ValidationError as e:
                logger.warning("Skipping malformed PropLine outcome for %s: %s", name, e)
    return return_list


def _team_side(outcome: dict, home_team: str, away_team: str) -> str | None:
    """home/away for a moneyline or puck line outcome. Books spell teams their own way, so PropLine's `side` is
    used when set, then the event's spelling, then a shared last word ("Canadiens")."""
    side = str(outcome.get("side") or "").lower()
    if side in ("home", "away"):
        return side
    name = normalize_name(outcome.get("name") or "")
    home, away = normalize_name(home_team), normalize_name(away_team)
    if name == home:
        return "home"
    if name == away:
        return "away"
    last = name.split(" ")[-1] if name else ""
    if last and last == home.split(" ")[-1] and last != away.split(" ")[-1]:
        return "home"
    if last and last == away.split(" ")[-1] and last != home.split(" ")[-1]:
        return "away"
    return None


def parse_game_lines(results: dict) -> list[GameLineResponse]:
    """Flattens an event odds payload into game-line quotes: each book's main moneyline, puck line and total.
    Team totals (a `totals` market with a team), alternate lines and 3-way moneylines are skipped."""
    event_id = str(results.get("id") or "")
    home_team, away_team = results.get("home_team") or "", results.get("away_team") or ""
    out = []
    for book_key, bookmaker, market in _live_markets(results):
        key = market.get("key")
        if key not in GAME_MARKETS or market.get("team") or (market.get("line_type") or "main") != "main":
            continue
        outcomes = market.get("outcomes", []) or []
        if any(str(o.get("side") or "").lower() == "draw" or str(o.get("name") or "").strip().lower() in ("tie", "draw")
               for o in outcomes):
            continue    # Bovada's 3-way (regulation) moneyline rides the h2h key too: not the 2-way price
        book_last_update = market.get("last_update") or bookmaker.get("last_update")
        for outcome in outcomes:
            if key == "totals":
                side = {"Over": "over", "Under": "under"}.get(str(outcome.get("name") or "").strip().title())
            else:
                side = _team_side(outcome, home_team, away_team)
            if side is None or outcome.get("price") is None or not book_key:
                continue
            point = outcome.get("point")
            if key != "h2h" and point is None:
                continue
            try:
                out.append(GameLineResponse(event_id=event_id, market=key, side=side,
                                            line=0.0 if key == "h2h" else point, odds=outcome["price"],
                                            bookmaker=book_key,
                                            book_last_update=outcome.get("book_updated_at") or book_last_update))
            except ValidationError as e:
                logger.warning("Skipping malformed PropLine game line for event %s: %s", event_id, e)
    return out
