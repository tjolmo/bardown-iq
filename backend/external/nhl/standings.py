"""The league standings from NHL's standings/now feed, cached for the site's teams page.

Not stored: the feed is one request for all 32 teams and changes only as games end, so page views share a fetch
for STANDINGS_CACHE_TTL_SECONDS. A failed fetch keeps serving the last good standings (marked stale by their
fetched_at) rather than an empty page."""
import asyncio
import datetime
import time

from pydantic import BaseModel, Field, field_validator

from external.http import get_with_retries

STANDINGS_URL = "https://api-web.nhle.com/v1/standings/now"
STANDINGS_CACHE_TTL_SECONDS = 10 * 60


def _default(v):
    """The feed's localized strings come as {"default": "..."}; a plain string is passed through."""
    if isinstance(v, dict):
        return v.get("default")
    return v


class TeamStanding(BaseModel):
    """One team's line in the standings (regular season)."""
    tri_code: str = Field(alias="teamAbbrev")
    name: str = Field(alias="teamName")
    nickname: str | None = Field(default=None, alias="teamCommonName")
    city: str | None = Field(default=None, alias="placeName")
    conference: str = Field(alias="conferenceName")      # Eastern / Western
    division: str = Field(alias="divisionName")          # Atlantic / Metropolitan / Central / Pacific
    games_played: int = Field(alias="gamesPlayed")
    wins: int
    losses: int
    ot_losses: int = Field(alias="otLosses")
    points: int
    regulation_wins: int = Field(default=0, alias="regulationWins")
    regulation_plus_ot_wins: int = Field(default=0, alias="regulationPlusOtWins")
    goals_for: int = Field(default=0, alias="goalFor")
    goals_against: int = Field(default=0, alias="goalAgainst")
    goal_differential: int = Field(default=0, alias="goalDifferential")
    streak_code: str | None = Field(default=None, alias="streakCode")   # W / L / OT
    streak_count: int | None = Field(default=None, alias="streakCount")
    l10_wins: int = Field(default=0, alias="l10Wins")
    l10_losses: int = Field(default=0, alias="l10Losses")
    l10_ot_losses: int = Field(default=0, alias="l10OtLosses")
    # the NHL's own ordering, tie-breaks included: 1 is first
    division_rank: int = Field(alias="divisionSequence")
    conference_rank: int = Field(alias="conferenceSequence")
    league_rank: int = Field(alias="leagueSequence")
    wildcard_rank: int = Field(default=0, alias="wildcardSequence")     # 0 for a team in a division's top three
    clinch: str | None = Field(default=None, alias="clinchIndicator")   # x / y / z / p, or e (eliminated)
    season_id: int = Field(alias="seasonId")

    @field_validator("tri_code", "name", "nickname", "city", mode="before")
    @classmethod
    def extract_default(cls, v):
        return _default(v)

    class Config:
        validate_by_name = True


class Standings(BaseModel):
    """Every team's line, as the feed ordered them (league rank), and when the feed was fetched."""
    as_of: datetime.datetime               # when the feed said the standings were current
    fetched_at: datetime.datetime          # when we fetched them
    season_id: int | None
    teams: list[TeamStanding]


def parse_standings(payload: dict, fetched_at: datetime.datetime) -> Standings:
    """The feed's JSON as Standings. A team line that fails validation is skipped, not fatal."""
    teams = []
    for row in payload.get("standings") or []:
        try:
            teams.append(TeamStanding(**row))
        except Exception as e:
            print(f"Skipping a standings line ({_default(row.get('teamAbbrev'))}): {e}")
    as_of = fetched_at
    raw_as_of = payload.get("standingsDateTimeUtc")
    if raw_as_of:
        try:
            as_of = datetime.datetime.fromisoformat(str(raw_as_of).replace("Z", "+00:00"))
            if as_of.tzinfo is None:
                as_of = as_of.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            pass
    return Standings(as_of=as_of, fetched_at=fetched_at, season_id=teams[0].season_id if teams else None, teams=teams)


# (monotonic time fetched, standings); only successful fetches replace it
_standings_cache: tuple[float, Standings] | None = None
_standings_lock = asyncio.Lock()


async def _fetch_standings() -> Standings | None:
    try:
        response = await get_with_retries(STANDINGS_URL)
        response.raise_for_status()
        payload = response.json()
    except Exception as e:
        print(f"Error scraping standings: {e}")
        return None
    standings = parse_standings(payload, datetime.datetime.now(datetime.timezone.utc))
    return standings if standings.teams else None


async def get_standings(max_age_seconds: float = STANDINGS_CACHE_TTL_SECONDS) -> Standings | None:
    """The current standings, reusing a fetch younger than max_age_seconds. When the feed can't be fetched the last
    good standings are returned (their fetched_at says how old); None only when there has never been one."""
    global _standings_cache
    async with _standings_lock:
        if _standings_cache is not None and time.monotonic() - _standings_cache[0] < max_age_seconds:
            return _standings_cache[1]
        standings = await _fetch_standings()
        if standings is not None:
            _standings_cache = (time.monotonic(), standings)
            return standings
        return _standings_cache[1] if _standings_cache is not None else None
