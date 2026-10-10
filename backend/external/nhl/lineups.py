"""Who dressed, who was scratched and every shift of a game, from the NHL API.

What the NHL exposes (probed Oct 2026):
  stats shiftcharts  https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId={id}
                     every shift of every player: playerId, teamAbbrev, period, startTime / endTime ("MM:SS" into the
                     period). typeCode 517 rows are shifts; 505 rows are goal events (no ice time). Filled in as a game
                     is played; empty before puck drop and for a few old or broken games.
  play-by-play       rosterSpots: the dressed players (teamId, playerId, sweaterNumber, positionCode C/L/R/D/G, names),
                     empty until lineups are posted shortly before puck drop. Faceoff plays name the winning and losing
                     player.
  HTML TOI reports  https://www.nhl.com/scores/htmlreports/{season}/T{H,V}{game number}.HTM: the NHL's official
                     shift report for the home (TH) and visiting (TV) team, the same shifts as the shift chart. Used
                     when the shift chart comes back empty (16 of the first 69 games of 2026-27 did).
  right-rail         gameInfo.{awayTeam,homeTeam}.scratches: [{id, firstName, lastName}], empty until lineups are
                     posted, then kept. The NHL list has every rostered player who didn't dress, injured ones included,
                     so a healthy scratch is a scratch the injury report doesn't list.
The NHL publishes no line combinations; app/deployment.py rebuilds them from the shifts.
"""
from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass

from external.http import get_with_retries
from external.nhl.games import fetch_gamecenter, _text

SHIFT_CHART_URL = "https://api.nhle.com/stats/rest/en/shiftcharts"
SHIFT_TYPE_CODE = 517
POSITIONS = ("C", "L", "R", "D", "G")


@dataclass(frozen=True)
class Shift:
    player_id: int
    team: str
    period: int
    start: int   # seconds into the period
    end: int


@dataclass(frozen=True)
class RosterSpot:
    player_id: int
    team: str
    position: str            # C / L / R / D / G
    sweater_number: int | None
    first_name: str | None
    last_name: str | None


@dataclass(frozen=True)
class Scratch:
    player_id: int
    team: str
    first_name: str | None
    last_name: str | None


def _seconds(clock: str | None) -> int | None:
    """"MM:SS" -> seconds, None when missing or malformed."""
    try:
        minutes, seconds = (clock or "").split(":")
        return int(minutes) * 60 + int(seconds)
    except ValueError:
        return None


def parse_shifts(payload: dict | None) -> list[Shift]:
    """The shifts of a shift chart response, without goal events and without shifts missing a time or running
    backwards (the NHL occasionally posts a shift with no end time while a game is in progress)."""
    shifts = []
    for row in (payload or {}).get("data") or []:
        if row.get("typeCode") != SHIFT_TYPE_CODE or row.get("playerId") is None or not row.get("teamAbbrev"):
            continue
        start, end = _seconds(row.get("startTime")), _seconds(row.get("endTime"))
        if start is None or end is None or end <= start or not row.get("period"):
            continue
        shifts.append(Shift(player_id=int(row["playerId"]), team=row["teamAbbrev"], period=int(row["period"]),
                            start=start, end=end))
    return shifts


def _team_by_id(pbp: dict | None) -> dict[int, str]:
    return {(pbp or {}).get(side, {}).get("id"): (pbp or {}).get(side, {}).get("abbrev")
            for side in ("homeTeam", "awayTeam") if ((pbp or {}).get(side) or {}).get("abbrev")}


def parse_roster_spots(pbp: dict | None) -> list[RosterSpot]:
    """The dressed players of a game (empty until lineups are posted)."""
    team_by_id = _team_by_id(pbp)
    spots = []
    for s in (pbp or {}).get("rosterSpots") or []:
        team = team_by_id.get(s.get("teamId"))
        if team is None or s.get("playerId") is None or s.get("positionCode") not in POSITIONS:
            continue
        spots.append(RosterSpot(player_id=int(s["playerId"]), team=team, position=s["positionCode"],
                                sweater_number=s.get("sweaterNumber"), first_name=_text(s.get("firstName")),
                                last_name=_text(s.get("lastName"))))
    return spots


def parse_scratches(right_rail: dict | None, home: str, away: str) -> list[Scratch]:
    """The scratches the NHL lists for each team (right-rail has no team codes, so the game's are passed in)."""
    info = (right_rail or {}).get("gameInfo") or {}
    out = []
    for side, team in (("homeTeam", home), ("awayTeam", away)):
        for s in (info.get(side) or {}).get("scratches") or []:
            if s.get("id") is not None:
                out.append(Scratch(player_id=int(s["id"]), team=team, first_name=_text(s.get("firstName")),
                                   last_name=_text(s.get("lastName"))))
    return out


def parse_faceoffs(pbp: dict | None) -> dict[int, int]:
    """player_id -> faceoffs taken (won or lost); tells a natural centre from a centre playing the wing."""
    taken: dict[int, int] = {}
    for play in (pbp or {}).get("plays") or []:
        if play.get("typeDescKey") != "faceoff":
            continue
        d = play.get("details") or {}
        for key in ("winningPlayerId", "losingPlayerId"):
            if d.get(key) is not None:
                taken[int(d[key])] = taken.get(int(d[key]), 0) + 1
    return taken


_PLAYER_HEADING = re.compile(r'class="playerHeading[^"]*"[^>]*>\s*(\d+)\s+([^<]*)</td>', re.I)
_SHIFT_ROW = re.compile(r"<tr[^>]*>\s*<td[^>]*>\s*(\d+)\s*</td>\s*<td[^>]*>\s*([^<]+?)\s*</td>\s*"
                        r"<td[^>]*>\s*(\d+:\d\d)\s*/[^<]*</td>\s*<td[^>]*>\s*(\d+:\d\d)\s*/", re.I)
_PERIODS = {"OT": 4}


def parse_toi_report(page: str | None, team: str, numbers: dict[int, int]) -> list[Shift]:
    """The shifts of one team's HTML TOI report. Players are headed "8 TANEV, CHRIS"; the sweater number is matched
    to a player id through `numbers` (sweater number -> player id, the team's dressed players). Each shift row has
    the period ("OT" for overtime) and its start and end as "elapsed / remaining"; shootout rows are skipped."""
    shifts: list[Shift] = []
    if not page:
        return shifts
    headings = list(_PLAYER_HEADING.finditer(page))
    for i, heading in enumerate(headings):
        player_id = numbers.get(int(heading.group(1)))
        if player_id is None:
            continue
        block = page[heading.end():headings[i + 1].start() if i + 1 < len(headings) else len(page)]
        for row in _SHIFT_ROW.finditer(block):
            label = html.unescape(row.group(2)).strip().upper()
            period = _PERIODS.get(label) or (int(label) if label.isdigit() else None)
            start, end = _seconds(row.group(3)), _seconds(row.group(4))
            if period is None or start is None or end is None or end <= start:
                continue
            shifts.append(Shift(player_id=player_id, team=team, period=period, start=start, end=end))
    return shifts


def toi_report_url(game_id: int, side: str) -> str:
    """side "H" (home) or "V" (visitor)."""
    year = game_id // 1_000_000
    return f"https://www.nhl.com/scores/htmlreports/{year}{year + 1}/T{side}{game_id % 1_000_000:06d}.HTM"


async def fetch_toi_report(game_id: int, side: str) -> str | None:
    try:
        response = await get_with_retries(toi_report_url(game_id, side))
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error fetching T{side} report for game {game_id}: {e}")
        return None


def parse_last_period(pbp: dict | None) -> tuple[int, str] | None:
    """(number, type) of the period the game is in, or ended in: (3, "REG"), (4, "OT"), (5, "SO")."""
    period = (pbp or {}).get("periodDescriptor") or {}
    if not period.get("number"):
        return None
    return int(period["number"]), str(period.get("periodType") or "")


async def fetch_shift_chart(game_id: int) -> dict | None:
    try:
        response = await get_with_retries(SHIFT_CHART_URL, params={"cayenneExp": f"gameId={game_id}"})
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching shift chart for game {game_id}: {e}")
        return None


@dataclass
class GameLineupData:
    """Everything fetched about one game's lineups. None marks a fetch that failed (as opposed to empty)."""
    game_id: int
    home: str
    away: str
    roster_spots: list[RosterSpot] | None
    scratches: list[Scratch] | None
    shifts: list[Shift] | None
    faceoffs: dict[int, int]
    last_period: tuple[int, str] | None = None   # (number, REG / OT / SO) of the game's last period, per play-by-play


async def fetch_game_lineup_data(game_id: int, home: str, away: str, with_shifts: bool = True) -> GameLineupData:
    """Dressed players and faceoffs (play-by-play), scratches (right-rail) and, with_shifts, every shift."""
    pbp, rail, chart = await asyncio.gather(
        fetch_gamecenter(game_id, "play-by-play"), fetch_gamecenter(game_id, "right-rail"),
        fetch_shift_chart(game_id) if with_shifts else asyncio.sleep(0, None))
    spots = parse_roster_spots(pbp) if pbp is not None else None
    shifts = parse_shifts(chart) if chart is not None else None
    if with_shifts and not shifts and spots:
        # the shift chart is empty for some games; the HTML TOI reports carry the same shifts
        pages = await asyncio.gather(fetch_toi_report(game_id, "H"), fetch_toi_report(game_id, "V"))
        from_reports = []
        for team, page in zip((home, away), pages):
            numbers = {s.sweater_number: s.player_id for s in spots if s.team == team and s.sweater_number is not None}
            from_reports += parse_toi_report(page, team, numbers)
        if from_reports:
            shifts = from_reports
    return GameLineupData(
        game_id=game_id, home=home, away=away, roster_spots=spots,
        scratches=parse_scratches(rail, home, away) if rail is not None else None,
        shifts=shifts, faceoffs=parse_faceoffs(pbp), last_period=parse_last_period(pbp))
