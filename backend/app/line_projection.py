"""Projected lines for a team's next game, from how it deployed its players in its recent games (game_units /
game_lineups, rebuilt from NHL shift charts by app/deployment.py), its current roster and ESPN's injury report.

The NHL publishes no line combinations, and coaches change them often, so the projection leans on the most recent
games: game k back (k = 0 for the last one) weighs DECAY ** k, over the last WINDOW games with shifts.

1. Lineup. The lineup the NHL posted for the game when it is out (shortly before puck drop): "confirmed". Otherwise
   the last game's dressed players, minus anyone traded, sent down or listed out by the injury report, plus a
   regular coming back (a player whose average 5-on-5 ice time ranks him in the team's top nine forwards or top
   four defensemen) in place of the dressed player of his group who plays least. Holes are filled with the
   available player who played most recently and most, so a healthy scratch draws back in before a call-up.
2. Lines. Forwards are split into trios and defensemen into pairs by an exact search over every split, scoring each
   trio by the weighted seconds it played together at 5 on 5, plus half the seconds each two of its members shared
   with any third (so a line that lost a player keeps its remaining pair), minus a small penalty for mixing ice-time
   tiers (which decides the lines of players with no shared history). Lines are numbered by their members' average
   5-on-5 ice time.
3. Slots. A trio's left wing, centre and right wing come from the players' listed positions, with faceoffs taken
   marking the real centre; a pair's left and right sides from their shot.
4. Special teams. Power-play and penalty-kill units are grown greedily from the player with the most weighted
   power-play (penalty-kill) time, each time adding the available player who shared the most of it with the unit.
"""
from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache

from app.deployment import EV_DEFENSE, EV_FORWARDS, PK, PP, unit_players

DECAY = 0.5
WINDOW = 6
PAIR_WEIGHT = 0.5         # credit for two members' shared seconds with any third
TIER_PENALTY = 0.05       # per second of spread in the members' average 5-on-5 ice time
FORWARDS, DEFENSE = ("C", "L", "R"), ("D",)
# out of the lineup per the injury report; day-to-day players usually play
OUT_STATUSES = {"out", "ir", "ltir", "suspended"}
REGULAR_FORWARDS, REGULAR_DEFENSE = 9, 4
REGULAR_MIN_GAMES = 3
MIN_UNIT_SECONDS = 1


@dataclass
class PastGame:
    """One of the team's games: its dressed and scratched players (game_lineups rows) and units (game_units rows)."""
    game_id: int
    lineup: list[dict]
    units: list[dict] = field(default_factory=list)

    @property
    def has_shifts(self) -> bool:
        return any(r["status"] == "dressed" and r.get("toi") is not None for r in self.lineup)


@dataclass
class RosterPlayer:
    player_id: int
    position: str | None
    shoots: str | None = None


@dataclass
class Unit:
    """One projected line, pair or special-teams group. `slots` pairs a slot name with a player id."""
    name: str
    slots: list[tuple[str, int]]
    seconds_last_game: int = 0     # seconds this exact group played together in the last game (5 on 5 for lines)
    games_together: int = 0        # games of the window in which it played together for at least a minute

    @property
    def players(self) -> list[int]:
        return [p for _, p in self.slots]


@dataclass
class Projection:
    lineup_status: str                       # "confirmed" (posted by the NHL) / "projected"
    forwards: list[Unit]
    defense: list[Unit]
    power_play: list[Unit]
    penalty_kill: list[Unit]
    extras: list[int]                        # dressed but outside the lines (an 11th forward's partner, a 7th D)
    dressed: list[int]
    based_on: list[int]                      # game ids that weighed in, newest first
    changes: dict[str, list[int]] = field(default_factory=lambda: {"in": [], "out": []})   # vs the last lineup


def _weights(games: list[PastGame], decay: float = DECAY, window: int = WINDOW) -> dict[int, float]:
    """game_id -> weight, for the games with shifts among the newest `window`."""
    usable = [g for g in games if g.has_shifts][:window]
    return {g.game_id: decay ** k for k, g in enumerate(usable)}


def _weighted_units(games: list[PastGame], weights: dict[int, float], situation: str) -> dict[tuple[int, ...], float]:
    out: dict[tuple[int, ...], float] = defaultdict(float)
    for g in games:
        w = weights.get(g.game_id)
        if w is None:
            continue
        for u in g.units:
            if u["situation"] == situation and u["seconds"] >= MIN_UNIT_SECONDS:
                out[unit_players(u["unit"])] += w * u["seconds"]
    return out


def _pair_seconds(units: dict[tuple[int, ...], float]) -> dict[frozenset, float]:
    pairs: dict[frozenset, float] = defaultdict(float)
    for players, seconds in units.items():
        for a, b in itertools.combinations(players, 2):
            pairs[frozenset((a, b))] += seconds
    return pairs


def average_toi(games: list[PastGame], weights: dict[int, float], column: str) -> dict[int, float]:
    """player -> weighted mean of `column` (seconds) over the window games he dressed in."""
    total, weight = defaultdict(float), defaultdict(float)
    for g in games:
        w = weights.get(g.game_id)
        if w is None:
            continue
        for r in g.lineup:
            if r["status"] == "dressed" and r.get(column) is not None:
                total[r["player_id"]] += w * r[column]
                weight[r["player_id"]] += w
    return {p: total[p] / weight[p] for p in total}


def season_average_toi(games: list[PastGame], column: str = "toi_ev") -> dict[int, tuple[float, int]]:
    """player -> (plain mean of `column`, games) over every game given that he dressed in (with shifts)."""
    total, n = defaultdict(float), defaultdict(int)
    for g in games:
        for r in g.lineup:
            if r["status"] == "dressed" and r.get(column) is not None:
                total[r["player_id"]] += r[column]
                n[r["player_id"]] += 1
    return {p: (total[p] / n[p], n[p]) for p in total}


def best_partition(players: list[int], size: int, groups: int, score) -> list[tuple[int, ...]]:
    """The split of `players` into `groups` disjoint groups of `size` (players left over sit out) maximizing the sum
    of score(group). Exact: a memoized search over which players are still unplaced."""
    players = sorted(players)
    n = len(players)
    groups = min(groups, n // size)
    if groups == 0:
        return []
    group_score = {}

    @lru_cache(maxsize=None)
    def solve(mask: int, left: int) -> tuple[float, tuple]:
        if left == 0:
            return 0.0, ()
        remaining = [i for i in range(n) if mask >> i & 1]
        if len(remaining) < size * left:
            return float("-inf"), ()
        first, rest = remaining[0], remaining[1:]
        best = (float("-inf"), ())
        if len(remaining) - 1 >= size * left:            # `first` sits out
            best = solve(mask & ~(1 << first), left)
        for others in itertools.combinations(rest, size - 1):
            group = (first,) + others
            if group not in group_score:
                group_score[group] = score(tuple(players[i] for i in group))
            sub_mask = mask
            for i in group:
                sub_mask &= ~(1 << i)
            sub_score, sub_groups = solve(sub_mask, left - 1)
            total = group_score[group] + sub_score
            if total > best[0]:
                best = (total, (group,) + sub_groups)
        return best

    _, chosen = solve((1 << n) - 1, groups)
    solve.cache_clear()
    return [tuple(players[i] for i in group) for group in chosen]


def _group_score(exact: dict[tuple[int, ...], float], pairs: dict[frozenset, float], avg_ev: dict[int, float]):
    def score(group: tuple[int, ...]) -> float:
        together = exact.get(tuple(sorted(group)), 0.0)
        shared = sum(pairs.get(frozenset(pair), 0.0) for pair in itertools.combinations(group, 2))
        tiers = [avg_ev[p] for p in group if p in avg_ev]
        spread = max(tiers) - min(tiers) if len(tiers) > 1 else 0.0
        return together + PAIR_WEIGHT * shared - TIER_PENALTY * spread
    return score


FORWARD_SLOTS = ("LW", "C", "RW")


def forward_slots(trio: tuple[int, ...], positions: dict[int, str], shoots: dict[int, str],
                  faceoffs: dict[int, float]) -> list[tuple[str, int]]:
    """LW / C / RW for a trio: listed positions, the most faceoffs taken marking the centre, a centre on the wing
    going to his forehand side's opposite (a left shot on the right wing is common, so the shot only breaks ties)."""
    most = max((faceoffs.get(p, 0.0) for p in trio), default=0.0)

    def cost(player: int, slot: str) -> float:
        pos, shot = positions.get(player), shoots.get(player)
        if slot == "C":
            c = 0.0 if pos == "C" else 1.0
            return c - (0.8 * faceoffs.get(player, 0.0) / most if most > 0 else 0.0)
        side = "L" if slot == "LW" else "R"
        if pos == side:
            return 0.0
        if pos == "C":
            return 0.5 + (0.1 if shot and shot != side else 0.0)
        return 1.0 + (0.1 if shot and shot != side else 0.0)

    best = min(itertools.permutations(trio), key=lambda order: (sum(cost(p, s) for p, s in zip(order, FORWARD_SLOTS)), order))
    return list(zip(FORWARD_SLOTS, best))


def defense_slots(pair: tuple[int, ...], shoots: dict[int, str], avg_ev: dict[int, float]) -> list[tuple[str, int]]:
    """LD / RD: a left shot on the left; two players with the same shot keep the one who plays more on his side."""
    a, b = sorted(pair, key=lambda p: (-avg_ev.get(p, 0.0), p))
    if shoots.get(a) == "R" and shoots.get(b) != "R" or shoots.get(b) == "L" and shoots.get(a) != "L":
        a, b = b, a
    elif shoots.get(a) == shoots.get(b) == "R":
        a, b = b, a
    return [("LD", a), ("RD", b)]


def grow_unit(candidates: list[int], player_seconds: dict[int, float], pairs: dict[frozenset, float],
              size: int) -> list[int]:
    """A special-teams unit: the candidate with the most weighted time, then repeatedly the one who shared the most
    of it with the unit so far (his own time breaks ties). Candidates with no time at all are never picked."""
    pool = [p for p in candidates if player_seconds.get(p, 0.0) > 0]
    if not pool:
        return []
    unit = [max(pool, key=lambda p: (player_seconds[p], -p))]
    while len(unit) < size:
        rest = [p for p in pool if p not in unit]
        if not rest:
            break
        unit.append(max(rest, key=lambda p: (sum(pairs.get(frozenset((p, m)), 0.0) for m in unit),
                                             player_seconds[p], -p)))
    return unit


def _together(games: list[PastGame], weights: dict[int, float], situation: str, players: list[int]) -> tuple[int, int]:
    """(seconds the exact group played together in the newest game with shifts, games of the window in which it
    played together for at least a minute)."""
    key = tuple(sorted(players))
    newest, count = 0, 0
    ordered = [g for g in games if g.game_id in weights]
    for i, g in enumerate(ordered):
        seconds = sum(u["seconds"] for u in g.units if u["situation"] == situation and unit_players(u["unit"]) == key)
        if i == 0:
            newest = seconds
        if seconds >= 60:
            count += 1
    return newest, count


def _special_together(games: list[PastGame], weights: dict[int, float], situation: str,
                      players: list[int]) -> tuple[int, int]:
    """As _together, but a special-teams unit counts any group containing all its players (a 4-man unit inside a
    5-man power play with a changing fifth)."""
    members = set(players)
    newest, count = 0, 0
    ordered = [g for g in games if g.game_id in weights]
    for i, g in enumerate(ordered):
        seconds = sum(u["seconds"] for u in g.units
                      if u["situation"] == situation and members <= set(unit_players(u["unit"])))
        if i == 0:
            newest = seconds
        if seconds >= 60:
            count += 1
    return newest, count


def project_lineup(games: list[PastGame], roster: list[RosterPlayer], injured: dict[int, str],
                   posted: list[dict] | None = None, season_games: list[PastGame] | None = None,
                   decay: float = DECAY, window: int = WINDOW) -> Projection | None:
    """The projection for the team's next game. `games` are its recent games, newest first; `roster` its current
    players (empty when unknown: nobody is dropped as traded); `injured` maps player ids on the injury report to
    their status; `posted` is the next game's dressed lineup when the NHL has posted it; `season_games` (default
    `games`) decide who counts as a regular; `decay` and `window` weigh the games (see the module docstring). None
    when there is no lineup to start from."""
    weights = _weights(games, decay, window)
    last = next((g for g in games if any(r["status"] == "dressed" for r in g.lineup)), None)
    if last is None and not posted:
        return None
    positions: dict[int, str] = {p.player_id: p.position for p in roster if p.position}
    shoots: dict[int, str] = {p.player_id: p.shoots for p in roster if p.shoots}
    for g in reversed(games):                      # newest game's listed position wins
        for r in g.lineup:
            if r.get("position"):
                positions[r["player_id"]] = r["position"]
    for r in posted or []:
        if r.get("position"):
            positions[r["player_id"]] = r["position"]

    avg_ev = average_toi(games, weights, "toi_ev")
    season_ev = season_average_toi(season_games if season_games is not None else games)
    last_dressed = [r["player_id"] for r in last.lineup if r["status"] == "dressed"] if last else []

    if posted:
        status = "confirmed"
        dressed = [r["player_id"] for r in posted]
    else:
        status = "projected"
        dressed = _project_dressed(games, weights, roster, injured, positions, last_dressed, avg_ev, season_ev)

    skaters = [p for p in dressed if positions.get(p) != "G"]
    forwards = [p for p in skaters if positions.get(p) in FORWARDS]
    defense = [p for p in skaters if positions.get(p) in DEFENSE]
    # a skater with no known position plays where his group is short
    for p in skaters:
        if p not in forwards and p not in defense:
            (defense if len(defense) < 6 and len(forwards) >= 12 else forwards).append(p)

    faceoffs = average_toi(games, weights, "faceoffs")
    ev_f = _weighted_units(games, weights, EV_FORWARDS)
    ev_d = _weighted_units(games, weights, EV_DEFENSE)
    trios = best_partition(forwards, 3, 4, _group_score(ev_f, _pair_seconds(ev_f), avg_ev))
    pairs = best_partition(defense, 2, 3, _group_score(ev_d, _pair_seconds(ev_d), avg_ev))
    by_toi = lambda group: (-sum(avg_ev.get(p, 0.0) for p in group) / len(group), group)
    trios.sort(key=by_toi)
    pairs.sort(key=by_toi)

    forward_units = []
    for i, trio in enumerate(trios, 1):
        newest, count = _together(games, weights, EV_FORWARDS, list(trio))
        forward_units.append(Unit(f"F{i}", forward_slots(trio, positions, shoots, faceoffs), newest, count))
    defense_units = []
    for i, pair in enumerate(pairs, 1):
        newest, count = _together(games, weights, EV_DEFENSE, list(pair))
        defense_units.append(Unit(f"D{i}", defense_slots(pair, shoots, avg_ev), newest, count))

    special = {}
    for situation, size, prefix in ((PP, 5, "PP"), (PK, 4, "PK")):
        units = _weighted_units(games, weights, situation)
        per_player: dict[int, float] = defaultdict(float)
        for group, seconds in units.items():
            for p in group:
                per_player[p] += seconds
        pair_seconds = _pair_seconds(units)
        pool, built = list(skaters), []
        for i in (1, 2):
            unit = grow_unit(pool, per_player, pair_seconds, size)
            if len(unit) < size - 1:
                break
            pool = [p for p in pool if p not in unit]
            ordered = sorted(unit, key=lambda p: (positions.get(p) in DEFENSE, -per_player.get(p, 0.0)))
            newest, count = _special_together(games, weights, situation, ordered)
            built.append(Unit(f"{prefix}{i}", [("D" if positions.get(p) in DEFENSE else "F", p) for p in ordered],
                              newest, count))
        special[situation] = built

    placed = {p for u in forward_units + defense_units for p in u.players}
    return Projection(
        lineup_status=status, forwards=forward_units, defense=defense_units, power_play=special[PP],
        penalty_kill=special[PK], extras=[p for p in skaters if p not in placed], dressed=dressed,
        based_on=[g.game_id for g in games if g.game_id in weights],
        changes={"in": [p for p in dressed if p not in last_dressed],
                 "out": [p for p in last_dressed if p not in dressed]} if last_dressed else {"in": [], "out": []})


def _project_dressed(games: list[PastGame], weights: dict[int, float], roster: list[RosterPlayer],
                     injured: dict[int, str], positions: dict[int, str], last_dressed: list[int],
                     avg_ev: dict[int, float], season_ev: dict[int, tuple[float, int]]) -> list[int]:
    on_roster = {p.player_id for p in roster}
    out = {p for p, status in injured.items() if status in OUT_STATUSES}

    def available(p: int) -> bool:
        return p not in out and (not on_roster or p in on_roster)

    def group_of(p: int) -> str:
        pos = positions.get(p)
        return "G" if pos == "G" else "D" if pos in DEFENSE else "F"

    def season_toi(p: int) -> float:
        return season_ev[p][0] if p in season_ev else 0.0

    dressed = [p for p in last_dressed if available(p)]

    # a regular back from injury takes the place of the dressed player of his group who plays least
    for group, regulars in (("F", REGULAR_FORWARDS), ("D", REGULAR_DEFENSE)):
        ranked = sorted((p for p, (_, n) in season_ev.items() if group_of(p) == group and n >= REGULAR_MIN_GAMES),
                        key=lambda p: (-season_toi(p), p))[:regulars]
        for p in ranked:
            mates = [q for q in dressed if group_of(q) == group]
            if p in dressed or not available(p) or not mates:
                continue
            weakest = min(mates, key=lambda q: (avg_ev.get(q, season_toi(q)), q))
            if season_toi(p) > avg_ev.get(weakest, season_toi(weakest)):
                dressed[dressed.index(weakest)] = p

    def recency(p: int) -> tuple:
        """Who draws in first: dressed in more of the recent games (weighted), then more ice time."""
        played = sum(weights[g.game_id] for g in games if g.game_id in weights
                     for r in g.lineup if r["player_id"] == p and r["status"] == "dressed")
        return (played, season_toi(p), -p)

    # holes left by injuries, trades and send-downs: same group, most recent and most used first
    pool = list(on_roster) if on_roster else list(season_ev)
    for group in ("F", "D", "G"):
        wanted = sum(group_of(p) == group for p in last_dressed)
        have = sum(group_of(p) == group for p in dressed)
        candidates = sorted((p for p in pool if p not in dressed and available(p) and group_of(p) == group),
                            key=recency, reverse=True)
        dressed += candidates[:max(0, wanted - have)]
    return dressed
