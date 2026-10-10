import asyncio
import datetime
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from external.nhl import standings as standings_module
from external.nhl.standings import parse_standings, get_standings
from app.routers.teams_router import split_team_name, standing_out

FETCHED = datetime.datetime(2026, 10, 10, 18, 0, tzinfo=datetime.timezone.utc)


def feed_line(tri="VGK", name="Vegas Golden Knights", common="Golden Knights", place="Vegas", conf="Western",
              div="Pacific", gp=5, w=4, l=1, otl=0, pts=8, div_seq=1, conf_seq=1, league_seq=1, wc=0, **extra):
    line = {
        "teamAbbrev": {"default": tri}, "teamName": {"default": name, "fr": name}, "teamCommonName": {"default": common},
        "placeName": {"default": place}, "conferenceName": conf, "conferenceAbbrev": conf[0],
        "divisionName": div, "divisionAbbrev": div[0], "gamesPlayed": gp, "wins": w, "losses": l, "otLosses": otl,
        "points": pts, "regulationWins": 3, "regulationPlusOtWins": 3, "goalFor": 21, "goalAgainst": 13,
        "goalDifferential": 8, "streakCode": "W", "streakCount": 3, "l10Wins": w, "l10Losses": l, "l10OtLosses": otl,
        "divisionSequence": div_seq, "conferenceSequence": conf_seq, "leagueSequence": league_seq,
        "wildcardSequence": wc, "seasonId": 20262027,
    }
    line.update(extra)
    return line


def payload(*lines, as_of="2026-10-10T17:15:00Z"):
    return {"standingsDateTimeUtc": as_of, "wildCardIndicator": True, "standings": list(lines)}


def test_parse_standings_reads_the_feed():
    s = parse_standings(payload(feed_line(), feed_line("NYR", "New York Rangers", "Rangers", "NY Rangers", "Eastern",
                                                       "Metropolitan", div_seq=1, conf_seq=1, league_seq=2)), FETCHED)
    assert s.season_id == 20262027
    assert s.as_of == datetime.datetime(2026, 10, 10, 17, 15, tzinfo=datetime.timezone.utc)
    assert s.fetched_at == FETCHED
    assert [t.tri_code for t in s.teams] == ["VGK", "NYR"]
    vgk = s.teams[0]
    assert (vgk.name, vgk.nickname, vgk.city) == ("Vegas Golden Knights", "Golden Knights", "Vegas")
    assert (vgk.conference, vgk.division) == ("Western", "Pacific")
    assert (vgk.wins, vgk.losses, vgk.ot_losses, vgk.points, vgk.games_played) == (4, 1, 0, 8, 5)
    assert (vgk.division_rank, vgk.conference_rank, vgk.league_rank, vgk.wildcard_rank) == (1, 1, 1, 0)
    assert vgk.clinch is None
    assert (vgk.streak_code, vgk.streak_count) == ("W", 3)


def test_parse_standings_skips_a_bad_line_and_reads_the_clinch():
    bad = feed_line("BOS", "Boston Bruins", "Bruins", "Boston")
    del bad["wins"]
    s = parse_standings(payload(feed_line(), bad, feed_line("CAR", "Carolina Hurricanes", "Hurricanes", "Carolina",
                                                             "Eastern", "Metropolitan", clinchIndicator="x")), FETCHED)
    assert [t.tri_code for t in s.teams] == ["VGK", "CAR"]
    assert s.teams[1].clinch == "x"


def test_parse_standings_without_a_date_uses_the_fetch_time():
    s = parse_standings({"standings": [feed_line()]}, FETCHED)
    assert s.as_of == FETCHED
    assert parse_standings({"standings": []}, FETCHED).season_id is None


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture
def fake_feed(monkeypatch):
    state = {"calls": 0, "payload": payload(feed_line()), "fail": False}

    async def fake_get(url, params=None, **kwargs):
        state["calls"] += 1
        if state["fail"]:
            raise RuntimeError("boom")
        return FakeResponse(state["payload"])

    monkeypatch.setattr(standings_module, "get_with_retries", fake_get)
    monkeypatch.setattr(standings_module, "_standings_cache", None)
    return state


def test_standings_are_fetched_once_within_the_ttl(fake_feed):
    first = asyncio.run(get_standings())
    second = asyncio.run(get_standings())
    assert first is second
    assert fake_feed["calls"] == 1
    assert [t.tri_code for t in first.teams] == ["VGK"]


def test_a_stale_cache_is_refetched(fake_feed):
    asyncio.run(get_standings())
    fake_feed["payload"] = payload(feed_line("EDM", "Edmonton Oilers", "Oilers", "Edmonton"))
    fresh = asyncio.run(get_standings(max_age_seconds=0))
    assert fake_feed["calls"] == 2
    assert [t.tri_code for t in fresh.teams] == ["EDM"]


def test_a_failed_fetch_keeps_the_last_good_standings(fake_feed):
    assert asyncio.run(get_standings()) is not None
    fake_feed["fail"] = True
    kept = asyncio.run(get_standings(max_age_seconds=0))
    assert kept is not None and [t.tri_code for t in kept.teams] == ["VGK"]
    assert fake_feed["calls"] == 2


def test_a_failed_first_fetch_is_none_and_not_cached(fake_feed):
    fake_feed["fail"] = True
    assert asyncio.run(get_standings()) is None
    fake_feed["fail"] = False
    assert asyncio.run(get_standings()) is not None
    assert fake_feed["calls"] == 2


def test_an_empty_feed_is_not_cached(fake_feed):
    fake_feed["payload"] = {"standings": []}
    assert asyncio.run(get_standings()) is None
    fake_feed["payload"] = payload(feed_line())
    assert asyncio.run(get_standings()) is not None


@pytest.mark.parametrize("name, city, nickname", [
    ("Toronto Maple Leafs", "Toronto", "Maple Leafs"),
    ("Columbus Blue Jackets", "Columbus", "Blue Jackets"),
    ("New York Rangers", "New York", "Rangers"),
    ("St. Louis Blues", "St. Louis", "Blues"),
    ("Utah Mammoth", "Utah", "Mammoth"),
])
def test_split_team_name(name, city, nickname):
    assert split_team_name(name) == (city, nickname)


def test_standing_out_formats_the_streak_and_last_ten():
    line = parse_standings(payload(feed_line(w=4, l=1, otl=0)), FETCHED).teams[0]
    out = standing_out(line)
    assert (out.streak, out.last10) == ("W3", "4-1-0")
    assert (out.wins, out.losses, out.otLosses, out.points) == (4, 1, 0, 8)
    assert (out.divisionRank, out.wildcardRank, out.clinch) == (1, 0, None)
    line = parse_standings(payload(feed_line(streakCode=None, streakCount=None)), FETCHED).teams[0]
    assert standing_out(line).streak is None
