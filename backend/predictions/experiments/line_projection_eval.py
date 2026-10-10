"""How well do projected lines match the lines teams then played? (RESULTS_lines.md)

    python -m predictions.experiments.line_projection_eval [--season 2026]

Rolling origin over every team's games with shift charts: game i is projected from games before it and compared
with what the team ran in game i, read off game i's own shifts the same way (its most-used trios, pairs and units).

* Lines given the lineup: the projection is handed game i's dressed players (as when the NHL has posted the lineup),
  so only the line building is scored. "lines exact": actual trios (pairs) the projection got exactly; "pairs kept":
  of every two players on the same actual line, the share the projection also put on one line (credit for a line
  that is two-thirds right).
* Lineup: no lineup handed over, no roster and no injury report (neither is stored historically), so this is a floor
  for the live projection: the share of game i's dressed skaters the projection dressed.
* PP1 / PK1: players shared between the projected and actual first units, over the unit size.

Each setting of the recency decay and window is scored; "last game" (window 1) is the baseline of copying the
previous game's lines.
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
from collections import defaultdict

from sqlalchemy import select

from app.crud.lineups import DRESSED, load_lineups, load_units
from app.database import AsyncSessionLocal
from app.line_projection import PastGame, project_lineup
from app.models import GameLineup, Games

SETTINGS = [("last game", 1.0, 1), ("decay 0.3", 0.3, 6), ("decay 0.5", 0.5, 6), ("decay 0.7", 0.7, 6),
            ("flat 3", 1.0, 3), ("flat 6", 1.0, 6)]
MIN_HISTORY = 2


def line_accuracy(projected: list[list[int]], actual: list[list[int]]) -> tuple[int, int, int, int]:
    """(actual groups matched exactly, actual groups, actual same-line pairs also together in the projection,
    actual same-line pairs)."""
    together = {frozenset(pair) for g in projected for pair in itertools.combinations(g, 2)}
    pairs = [frozenset(pair) for g in actual for pair in itertools.combinations(g, 2)]
    exact = sum(frozenset(g) in {frozenset(x) for x in projected} for g in actual)
    return exact, len(actual), sum(p in together for p in pairs), len(pairs)


async def team_games(db, season: int) -> dict[str, list[PastGame]]:
    """team -> its games with shifts, oldest first."""
    stmt = (select(Games.id, GameLineup.team).join(GameLineup, GameLineup.game_id == Games.id)
            .where(Games.season == season * 10000 + season + 1, GameLineup.toi.is_not(None)).distinct()
            .order_by(Games.start_time, Games.id))
    by_team: dict[str, list[int]] = defaultdict(list)
    for gid, team in (await db.execute(stmt)).all():
        by_team[team].append(gid)
    out = {}
    for team, ids in by_team.items():
        lineups, units = defaultdict(list), defaultdict(list)
        for r in await load_lineups(db, team, ids):
            lineups[r["game_id"]].append(r)
        for u in await load_units(db, team, ids):
            units[u["game_id"]].append(u)
        out[team] = [PastGame(gid, lineups[gid], units[gid]) for gid in ids]
    return out


def evaluate(teams: dict[str, list[PastGame]]) -> dict[str, dict[str, float]]:
    results = {}
    for name, decay, window in SETTINGS:
        tally = defaultdict(int)
        for games in teams.values():
            for i in range(MIN_HISTORY, len(games)):
                game, before = games[i], games[:i][::-1]
                dressed = [r for r in game.lineup if r["status"] == DRESSED]
                actual = project_lineup([game], [], {}, posted=dressed, window=1)
                given = project_lineup(before, [], {}, posted=dressed, decay=decay, window=window)
                blind = project_lineup(before, [], {}, decay=decay, window=window)
                if actual is None or given is None or blind is None:
                    continue
                for kind, proj_units, act_units in (("F", given.forwards, actual.forwards),
                                                    ("D", given.defense, actual.defense)):
                    e, n, kept, pairs = line_accuracy([u.players for u in proj_units], [u.players for u in act_units])
                    tally[f"{kind}_exact"] += e
                    tally[f"{kind}_groups"] += n
                    tally[f"{kind}_kept"] += kept
                    tally[f"{kind}_pairs"] += pairs
                for kind, proj_units, act_units in (("PP1", given.power_play, actual.power_play),
                                                    ("PK1", given.penalty_kill, actual.penalty_kill)):
                    if act_units and proj_units:
                        tally[f"{kind}_shared"] += len(set(proj_units[0].players) & set(act_units[0].players))
                        tally[f"{kind}_size"] += len(act_units[0].players)
                skaters = {r["player_id"] for r in dressed if r.get("position") != "G"}
                tally["lineup_right"] += len(skaters & set(blind.dressed))
                tally["lineup_total"] += len(skaters)
                tally["games"] += 1
        results[name] = {
            "team-games": tally["games"],
            "F lines exact": tally["F_exact"] / max(tally["F_groups"], 1),
            "F pairs kept": tally["F_kept"] / max(tally["F_pairs"], 1),
            "D pairs exact": tally["D_exact"] / max(tally["D_groups"], 1),
            "PP1 players": tally["PP1_shared"] / max(tally["PP1_size"], 1),
            "PK1 players": tally["PK1_shared"] / max(tally["PK1_size"], 1),
            "lineup (blind)": tally["lineup_right"] / max(tally["lineup_total"], 1),
        }
    return results


async def main(season: int):
    async with AsyncSessionLocal() as db:
        teams = await team_games(db, season)
    results = evaluate(teams)
    columns = list(next(iter(results.values())))
    print("| setting | " + " | ".join(columns) + " |")
    print("|---|" + "---|" * len(columns))
    for name, row in results.items():
        print(f"| {name} | " + " | ".join(f"{v:.1%}" if isinstance(v, float) else str(v) for v in row.values()) + " |")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=None, help="season start year (default: the current season)")
    args = parser.parse_args()
    from app.schedules import get_current_season_start_year
    asyncio.run(main(args.season or get_current_season_start_year()))
