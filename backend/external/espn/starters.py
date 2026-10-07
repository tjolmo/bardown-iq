"""Probable / confirmed starting goalies from ESPN's scoreboard.

    https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates=YYYYMMDD

Each competitor carries `probables: [{name: "probableStartingGoalie", athlete: {...}, status: {type}}]`, with
status type "expected" (ESPN's projection, posted a day or more ahead) or "confirmed" (announced by the team,
usually after the morning skate). After the game the entry shows the goalie who started, as "confirmed".
The NHL's own API has no pre-game starter field (see external/nhl/games.py), so this is the pre-game source.
Same unofficial ESPN API the odds and props backfills already use.

ESPN ids are not NHL ids, so each pick is matched to the NHL goalies rostered for the game (gamecenter landing /
play-by-play) by team, name and sweater number.
"""
from __future__ import annotations

import datetime
from typing import Iterable

from app.name_matching import normalize_name
from external.espn.odds import SCOREBOARD_URL, to_nhl_code
from external.http import get_with_retries
from external.nhl.response_models import GameGoalie, StarterPick

ESPN_STATUS = {"confirmed": "confirmed", "expected": "probable"}


def parse_probable_goalies(payload: dict | None) -> list[dict]:
    """One dict per (event, team) with a probable goalie: home, away, team (NHL tri codes), start (UTC datetime),
    espn_id, full_name, short_name, jersey, status ("confirmed" | "probable")."""
    out = []
    for event in (payload or {}).get("events") or []:
        comp = (event.get("competitions") or [{}])[0]
        sides = {c.get("homeAway"): c for c in comp.get("competitors") or []}
        home = to_nhl_code(((sides.get("home") or {}).get("team") or {}).get("abbreviation"))
        away = to_nhl_code(((sides.get("away") or {}).get("team") or {}).get("abbreviation"))
        if not home or not away:
            continue
        try:
            start = datetime.datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
        except (KeyError, ValueError, AttributeError):
            start = None
        for side, team in (("home", home), ("away", away)):
            for p in (sides.get(side) or {}).get("probables") or []:
                if p.get("name") != "probableStartingGoalie":
                    continue
                athlete = p.get("athlete") or {}
                status_type = ((p.get("status") or {}).get("type") or "").lower()
                jersey = athlete.get("jersey")
                out.append({
                    "home": home, "away": away, "team": team, "start": start,
                    "espn_id": athlete.get("id") or p.get("playerId"),
                    "full_name": athlete.get("fullName") or athlete.get("displayName"),
                    "short_name": athlete.get("shortName"),
                    "jersey": int(jersey) if str(jersey or "").isdigit() else None,
                    "status": ESPN_STATUS.get(status_type, "probable"),
                })
    return out


async def fetch_probable_goalies(dates: Iterable[datetime.date]) -> list[dict]:
    """ESPN probables for each date (ESPN's scoreboard dates are US Eastern game days)."""
    out = []
    for d in dates:
        try:
            response = await get_with_retries(SCOREBOARD_URL, params={"dates": d.strftime("%Y%m%d")})
            response.raise_for_status()
            out.extend(parse_probable_goalies(response.json()))
        except Exception as e:
            print(f"Error fetching ESPN probable goalies for {d}: {e}")
    return out


def _last_name(full_name: str | None) -> str:
    parts = (full_name or "").split()
    return normalize_name(parts[-1]) if parts else ""


def match_goalie(pick: dict, goalies: list[GameGoalie]) -> GameGoalie | None:
    """The NHL goalie on the pick's team that ESPN means: full name, else unique last name (jersey breaks ties),
    else a unique jersey number when the name is missing."""
    team = [g for g in goalies if g.team == pick["team"]]
    full = normalize_name(pick.get("full_name") or "")
    exact = [g for g in team if normalize_name(f"{g.first_name or ''} {g.last_name or ''}") == full]
    if len(exact) == 1:
        return exact[0]
    last = _last_name(pick.get("full_name"))
    same_last = [g for g in team if last and normalize_name(g.last_name or "") == last]
    if len(same_last) > 1 and pick.get("jersey") is not None:
        same_last = [g for g in same_last if g.sweater_number == pick["jersey"]]
    if len(same_last) == 1:
        return same_last[0]
    if not full and pick.get("jersey") is not None:
        by_number = [g for g in team if g.sweater_number == pick["jersey"]]
        if len(by_number) == 1:
            return by_number[0]
    return None


def resolve_starters(game_id: int, home: str, away: str, picks: list[dict], goalies: list[GameGoalie],
                     pbp_starters: dict[str, int]) -> tuple[list[StarterPick], list[str]]:
    """Starters for one game, best source first: the goalie actually in net once the game has started (NHL
    play-by-play; stored as the actual starter beside any earlier ESPN pick), else ESPN's confirmed / expected goalie matched to an NHL id. An ESPN goalie who is not among
    the dressed goalies (once lineups are posted) is dropped. Returns (picks, problems)."""
    out, problems = [], []
    by_team = {p["team"]: p for p in picks if p["home"] == home and p["away"] == away}
    for team in (home, away):
        if team in pbp_starters:
            out.append(StarterPick(game_id=game_id, team=team, player_id=pbp_starters[team], status="actual", source="nhl"))
            continue
        pick = by_team.get(team)
        if pick is None:
            problems.append(f"{game_id} {team}: no ESPN probable goalie")
            continue
        goalie = match_goalie(pick, goalies)
        if goalie is None:
            problems.append(f"{game_id} {team}: ESPN goalie {pick.get('full_name')!r} not matched to the NHL roster")
            continue
        if goalie.dressed is False:
            problems.append(f"{game_id} {team}: ESPN goalie {pick.get('full_name')!r} is not dressed")
            continue
        out.append(StarterPick(game_id=game_id, team=team, player_id=goalie.player_id, status=pick["status"], source="espn"))
    return out, problems
