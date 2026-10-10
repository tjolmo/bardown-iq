"""How a team deployed its players in one game, rebuilt from the NHL shift chart (external/nhl/lineups.py).

The shift chart only says when each player was on the ice. Walking the game second by second gives who was on the
ice together and at what strength:
  ev  5 on 5, both goalies in net
  pp  the team has more skaters than the opponent and the opponent is short (5v4, 5v3, 4v3), both goalies in net
  pk  the mirror of pp
Anything else (4 on 4, 3 on 3 overtime, an empty net) only counts toward a player's total ice time.

Units are counted per second of that strength: the three forwards on together at 5 on 5 (ev_f), the two defensemen
(ev_d), the power-play group (pp, every skater on: 4 or 5) and the penalty-kill group (pk, 3 or 4). A second with an
odd group (two forwards and three defensemen, a change in progress) counts toward ice time but no unit.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from external.nhl.lineups import Shift

EV, PP, PK = "ev", "pp", "pk"
EV_FORWARDS, EV_DEFENSE = "ev_f", "ev_d"
SITUATIONS = (EV_FORWARDS, EV_DEFENSE, PP, PK)
FORWARD_POSITIONS = ("C", "L", "R")
FULL_STRENGTH = 5


def unit_key(player_ids) -> str:
    """A unit's stored key: its player ids sorted and joined with "-"."""
    return "-".join(str(p) for p in sorted(player_ids))


def unit_players(key: str) -> tuple[int, ...]:
    return tuple(int(p) for p in key.split("-")) if key else ()


@dataclass
class TeamDeployment:
    """One team's game: seconds per player by strength and seconds per unit."""
    toi: dict[int, int] = field(default_factory=lambda: defaultdict(int))         # every second on the ice
    toi_ev: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    toi_pp: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    toi_pk: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    units: dict[str, Counter] = field(default_factory=lambda: {s: Counter() for s in SITUATIONS})


def _on_ice_by_second(shifts: list[Shift]) -> dict[int, list[dict[str, set[int]]]]:
    """period -> per second -> team -> players on the ice. Shifts are half-open [start, end), so a change on the
    same second never puts both lines on the ice."""
    length: dict[int, int] = defaultdict(int)
    for s in shifts:
        length[s.period] = max(length[s.period], s.end)
    seconds = {p: [defaultdict(set) for _ in range(n)] for p, n in length.items()}
    for s in shifts:
        timeline = seconds[s.period]
        for t in range(s.start, s.end):
            timeline[t][s.team].add(s.player_id)
    return seconds


def game_deployment(shifts: list[Shift], positions: dict[int, str], teams: tuple[str, str]) -> dict[str, TeamDeployment]:
    """team -> TeamDeployment for a game's shifts. `positions` maps player id to C/L/R/D/G (players without one
    count as skaters but never join a forward or defense unit); `teams` are the game's two tri codes."""
    out = {team: TeamDeployment() for team in teams}
    goalies = {pid for pid, pos in positions.items() if pos == "G"}
    for timeline in _on_ice_by_second(shifts).values():
        for on_ice in timeline:
            skaters = {team: {p for p in on_ice.get(team, ()) if p not in goalies} for team in teams}
            in_net = {team: any(p in goalies for p in on_ice.get(team, ())) for team in teams}
            for team in teams:
                dep = out[team]
                for p in on_ice.get(team, ()):
                    dep.toi[p] += 1
                if not all(in_net.values()):
                    continue
                opponent = teams[1] if team == teams[0] else teams[0]
                mine, theirs = len(skaters[team]), len(skaters[opponent])
                group = skaters[team]
                if mine == theirs == FULL_STRENGTH:
                    for p in group:
                        dep.toi_ev[p] += 1
                    forwards = [p for p in group if positions.get(p) in FORWARD_POSITIONS]
                    defense = [p for p in group if positions.get(p) == "D"]
                    if len(forwards) == 3 and len(defense) == 2:
                        dep.units[EV_FORWARDS][unit_key(forwards)] += 1
                        dep.units[EV_DEFENSE][unit_key(defense)] += 1
                elif mine > theirs and theirs < FULL_STRENGTH and mine <= FULL_STRENGTH:
                    for p in group:
                        dep.toi_pp[p] += 1
                    dep.units[PP][unit_key(group)] += 1
                elif mine < theirs and mine < FULL_STRENGTH and theirs <= FULL_STRENGTH:
                    for p in group:
                        dep.toi_pk[p] += 1
                    dep.units[PK][unit_key(group)] += 1
    return out


def shifts_cover_game(shifts: list[Shift], teams: tuple[str, str], min_players: int = 15) -> bool:
    """True when the shifts look like a whole game: both teams with shifts for at least `min_players` players in
    each of the three regulation periods (a game still being played, or a partial chart, is left for later)."""
    seen: dict[tuple[str, int], set[int]] = defaultdict(set)
    for s in shifts:
        seen[(s.team, s.period)].add(s.player_id)
    return all(len(seen[(team, period)]) >= min_players for team in teams for period in (1, 2, 3))


def unit_rows(game_id: int, deployments: dict[str, TeamDeployment], min_seconds: int = 1) -> list[dict]:
    """game_units rows: one per unit that played at least `min_seconds` together."""
    rows = []
    for team, dep in deployments.items():
        for situation, counter in dep.units.items():
            for key, seconds in counter.items():
                if seconds >= min_seconds:
                    rows.append({"game_id": game_id, "team": team, "situation": situation, "unit": key,
                                 "seconds": int(seconds)})
    return rows
