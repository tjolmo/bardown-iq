from external.nhl.response_models import GameResponse
from external.nhl.response_models import GameOdds, GameGoalie
import asyncio
import time
import httpx
from external.http import get_with_retries

async def fetch_and_get_players_in_a_game(game_id: int) -> list[int] | None:
    """Scrapes player data for a game from API, cleans, returns list of player IDs."""
    base_url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"
    ids = []
    try:
        response = await get_with_retries(base_url)
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

ODDS_CACHE_TTL_SECONDS = 90
MONEYLINE_DESCRIPTION = "MONEY_LINE_2_WAY_TNB"
# (monotonic time fetched, result); only successful fetches are cached
_odds_cache: tuple[float, list[GameOdds] | None] | None = None
_odds_lock = asyncio.Lock()

def _find_moneyline(odds_list: list[dict] | None) -> float | None:
    for odds in odds_list or []:
        if odds.get("description") == MONEYLINE_DESCRIPTION:
            return odds.get("value")
    return None

async def _fetch_odds_for_current_games() -> tuple[bool, list[GameOdds] | None]:
    """Returns (succeeded, odds). A failed request is (False, None)."""
    base_url = "https://api-web.nhle.com/v1/partner-game/US/now"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(base_url)
            response.raise_for_status()
            games = response.json().get("games")
        except Exception as e:
            print(f"Error scraping odds: {e}")
            return False, None
    if not games:
        return True, None

    return_odds = []
    for game in games:
        # looked up fresh for every game so a game without a moneyline can neither
        # raise UnboundLocalError nor inherit the previous game's odds
        home_moneyline = _find_moneyline((game.get("homeTeam") or {}).get("odds"))
        away_moneyline = _find_moneyline((game.get("awayTeam") or {}).get("odds"))
        if home_moneyline is None or away_moneyline is None:
            continue
        try:
            return_odds.append(GameOdds(game_id=game.get("gameId"), home_moneyline=home_moneyline, away_moneyline=away_moneyline))
        except Exception as e:
            print(f"Skipping odds for game {game.get('gameId')}: {e}")
    return True, return_odds

async def get_odds_for_current_games() -> list[GameOdds] | None:
    """Moneyline odds for today's games, cached for ODDS_CACHE_TTL_SECONDS so page views
    don't each make an external call. Failed fetches are not cached."""
    global _odds_cache
    async with _odds_lock:
        if _odds_cache is not None and time.monotonic() - _odds_cache[0] < ODDS_CACHE_TTL_SECONDS:
            return _odds_cache[1]
        succeeded, odds = await _fetch_odds_for_current_games()
        if succeeded:
            _odds_cache = (time.monotonic(), odds)
        return odds

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

# ---------- goalies / starters (gamecenter) ----------
# What the NHL API exposes about starters (probed Oct 2026):
#   landing  matchup.goalieComparison.{home,away}Team.leaders: every rostered goalie with season stats, before the
#            game; no starter or "probable" flag. Gone once the game is final.
#   play-by-play rosterSpots: the dressed players (both goalies per team), empty until lineups are posted around
#            puck drop; no starter flag. After puck drop, shot events carry details.goalieInNetId.
#   boxscore playerByGameStats: only once the game starts; goalies have toi, and finished games (every season back to
#            2008) carry a `starter` flag, which almost always matches the play-by-play's first shot faced (a starter
#            pulled early still counts); see parse_actual_starters for the rare disagreements.
#   right-rail: season series / coaches / scratches (empty pre-game); nothing on goalies.
# So the NHL API can tell who started only after puck drop; pre-game starters come from ESPN (external/espn/starters.py).


GAMECENTER_URL = "https://api-web.nhle.com/v1/gamecenter/{game_id}/{endpoint}"
SHOT_EVENTS = {"shot-on-goal", "missed-shot", "goal"}

def _text(v) -> str | None:
    return v.get("default") if isinstance(v, dict) else v

def parse_game_goalies(landing: dict | None, pbp: dict | None = None) -> list[GameGoalie]:
    """Rostered goalies per team from landing's goalie comparison, marked dressed or not once the play-by-play
    rosterSpots are posted (dressed goalies missing from the comparison, e.g. a same-day call-up, are added)."""
    src = landing or pbp or {}
    abbrev = {side: (src.get(side) or {}).get("abbrev") for side in ("homeTeam", "awayTeam")}
    goalies: dict[int, GameGoalie] = {}
    comparison = ((landing or {}).get("matchup") or {}).get("goalieComparison") or {}
    for side in ("homeTeam", "awayTeam"):
        for g in (comparison.get(side) or {}).get("leaders") or []:
            if g.get("playerId") is None or not abbrev[side] or g.get("positionCode", "G") != "G":
                continue
            goalies[int(g["playerId"])] = GameGoalie(player_id=int(g["playerId"]), team=abbrev[side],
                                                     first_name=_text(g.get("firstName")), last_name=_text(g.get("lastName")),
                                                     sweater_number=g.get("sweaterNumber"))
    if pbp:
        team_by_id = {(pbp.get(side) or {}).get("id"): (pbp.get(side) or {}).get("abbrev") for side in ("homeTeam", "awayTeam")}
        spots = pbp.get("rosterSpots") or []
        posted = {team_by_id.get(s.get("teamId")) for s in spots}
        dressed = {}
        for s in spots:
            team = team_by_id.get(s.get("teamId"))
            if s.get("positionCode") == "G" and team and s.get("playerId") is not None:
                dressed[int(s["playerId"])] = GameGoalie(player_id=int(s["playerId"]), team=team,
                                                         first_name=_text(s.get("firstName")), last_name=_text(s.get("lastName")),
                                                         sweater_number=s.get("sweaterNumber"), dressed=True)
        for pid, g in list(goalies.items()):
            if g.team in posted:
                goalies[pid] = g.model_copy(update={"dressed": pid in dressed})
        for pid, g in dressed.items():
            goalies.setdefault(pid, g)
    return list(goalies.values())

def parse_pbp_starters(pbp: dict | None) -> dict[str, int]:
    """Team tri code -> the goalie in net for the first shot that team faced. Only known after puck drop.
    Shots at an empty net carry no goalieInNetId and are skipped; shootout attempts are ignored (a team that faced no
    shot in regulation and overtime gets no starter rather than its shootout goalie). Every season back to 2008 has
    goalieInNetId on shot events, though 2008-09 only lists shots on goal and goals (no missed shots)."""
    if not pbp:
        return {}
    team_by_id = {(pbp.get(side) or {}).get("id"): (pbp.get(side) or {}).get("abbrev") for side in ("homeTeam", "awayTeam")}
    starters: dict[str, int] = {}
    for play in sorted(pbp.get("plays") or [], key=lambda p: p.get("sortOrder", 0)):
        d = play.get("details") or {}
        if play.get("typeDescKey") not in SHOT_EVENTS or d.get("goalieInNetId") is None:
            continue
        if (play.get("periodDescriptor") or {}).get("periodType") == "SO":
            continue
        shooter = team_by_id.get(d.get("eventOwnerTeamId"))
        defending = [t for t in team_by_id.values() if t and t != shooter]
        if shooter and len(defending) == 1 and defending[0] not in starters:
            starters[defending[0]] = int(d["goalieInNetId"])
        if len(starters) == 2:
            break
    return starters

def _boxscore_goalies(box: dict | None) -> dict[str, list[dict]]:
    stats = (box or {}).get("playerByGameStats") or {}
    return {((box or {}).get(side) or {}).get("abbrev"): (stats.get(side) or {}).get("goalies") or []
            for side in ("homeTeam", "awayTeam") if ((box or {}).get(side) or {}).get("abbrev")}

def parse_boxscore_starters(box: dict | None) -> dict[str, int]:
    """Team tri code -> the goalie the boxscore flags as `starter` (finished games only). A team with no flagged
    goalie, or more than one, is left out."""
    starters = {}
    for team, goalies in _boxscore_goalies(box).items():
        flagged = [g["playerId"] for g in goalies if g.get("starter") and g.get("playerId")]
        if len(flagged) == 1:
            starters[team] = int(flagged[0])
    return starters

def parse_actual_starters(box: dict | None, pbp: dict | None) -> tuple[dict[str, int], dict[str, str], dict[str, tuple]]:
    """Who started a played game, per team: the goalie in net for the first shot the team faced (play-by-play), else
    the boxscore's starter flag. Returns (starters, method per team: "pbp" / "boxscore", disagreements per team as
    (boxscore, pbp)). On 23,249 games from 2008 they disagreed 5 times (RESULTS_v5): twice the starter left injured
    before facing a shot (the flagged goalie faced none; the flag is right and the play-by-play names the reliever),
    three times the flag sat on the reliever of a starter pulled after 10-16 minutes (the play-by-play is right).
    So the flag wins only when its goalie played but faced no shots."""
    box_s, pbp_s = parse_boxscore_starters(box), parse_pbp_starters(pbp)
    shotless = {int(g["playerId"]) for goalies in _boxscore_goalies(box).values() for g in goalies
                if g.get("playerId") and g.get("shotsAgainst") == 0 and g.get("toi") not in (None, "00:00")}
    starters, method, disagree = {}, {}, {}
    for team in dict.fromkeys(list(pbp_s) + list(box_s)):
        if team in pbp_s and team in box_s and pbp_s[team] != box_s[team]:
            disagree[team] = (box_s[team], pbp_s[team])
        if team in pbp_s and not (team in disagree and box_s[team] in shotless):
            starters[team], method[team] = pbp_s[team], "pbp"
        else:
            starters[team], method[team] = box_s[team], "boxscore"
    return starters, method, disagree

async def fetch_gamecenter(game_id: int, endpoint: str) -> dict | None:
    try:
        response = await get_with_retries(GAMECENTER_URL.format(game_id=game_id, endpoint=endpoint))
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching {endpoint} for game {game_id}: {e}")
        return None

async def fetch_game_goalies(game_id: int) -> tuple[list[GameGoalie], dict[str, int]]:
    """(rostered goalies, starters known from the play-by-play once the game has started) for one game."""
    landing, pbp = await asyncio.gather(fetch_gamecenter(game_id, "landing"), fetch_gamecenter(game_id, "play-by-play"))
    return parse_game_goalies(landing, pbp), parse_pbp_starters(pbp)

async def fetch_actual_starters(game_id: int) -> tuple[dict[str, int], dict[str, str], dict[str, tuple]] | None:
    """parse_actual_starters for a played game, or None when neither the boxscore nor the play-by-play could be fetched."""
    box, pbp = await asyncio.gather(fetch_gamecenter(game_id, "boxscore"), fetch_gamecenter(game_id, "play-by-play"))
    if box is None and pbp is None:
        return None
    return parse_actual_starters(box, pbp)
