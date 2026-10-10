"""The roster page's lineup (GET /teams/{tri_code}/lineup): the next game's lines, goalies, injuries and scratches,
put together from game_lineups / game_units (NHL), the injury report (ESPN), game_starters and the roster."""
from __future__ import annotations

import datetime

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.game_starters import STATUS_RANK, load_game_starters
from app.crud.lineups import (DRESSED, SCRATCHED, get_next_team_game, get_recent_lineup_games, load_lineups,
                              load_units)
from app.crud.player_injuries import get_recently_listed_out, load_injury_report
from app.line_projection import OUT_STATUSES, WINDOW, PastGame, RosterPlayer, Unit, project_lineup
from app.models import GameLineup, Player
from app.schemas.teams import (LineupChangesOut, LineupGameOut, LineupGoalieOut, LineupPlayerOut, LineupUnitOut,
                               TeamInjuryOut, TeamLineupOut, TeamScratchOut)

# games of lineup history read: enough for a season's regulars; the lines weigh only the newest WINDOW with shifts
HISTORY_GAMES = 82
# extra games whose units are loaded beyond WINDOW, in case some of the newest have no shift chart
UNIT_SLACK = 4
# a player listed out within this long, and no longer listed, is back from injury
RETURN_LOOKBACK = datetime.timedelta(days=30)


def _nan_to_none(value):
    """None for missing values of any kind (None, NaN, NaT), as pandas leaves them in an injury report row."""
    try:
        return None if pd.isna(value) else value
    except (TypeError, ValueError):     # a list or array: not a scalar, never missing
        return value


class _People:
    """Display info for every player the response names: the players table, else the lineup rows (a same-day call-up
    may not be in players yet)."""

    def __init__(self, players: list[Player], lineup_rows: list[dict], injured: dict[int, str]):
        self.info: dict[int, dict] = {}
        for r in lineup_rows:
            self.info.setdefault(r["player_id"], {"firstName": r.get("first_name"), "lastName": r.get("last_name"),
                                                  "number": r.get("sweater_number"), "position": r.get("position")})
        for p in players:
            self.info[p.id] = {"firstName": p.first_name, "lastName": p.last_name, "number": p.number,
                               "position": p.position, "shoots": p.shoots_catches, "headshot": p.headshot}
        self.injured = injured

    def out(self, player_id: int, slot: str | None = None) -> LineupPlayerOut:
        return LineupPlayerOut(id=player_id, slot=slot, injuryStatus=self.injured.get(player_id),
                               **self.info.get(player_id, {}))


def _unit_out(unit: Unit, people: _People) -> LineupUnitOut:
    return LineupUnitOut(name=unit.name, players=[people.out(p, slot) for slot, p in unit.slots],
                         secondsLastGame=unit.seconds_last_game, gamesTogether=unit.games_together)


def _scratch_streak(player_id: int, games: list[PastGame]) -> int:
    streak = 0
    for g in games:
        status = next((r["status"] for r in g.lineup if r["player_id"] == player_id), None)
        if status != SCRATCHED:
            break
        streak += 1
    return streak


async def _starter(db: AsyncSession, team: str, game_id: int | None, last: PastGame | None) -> tuple[int | None, str]:
    """(goalie id, status) of the next game's starter: the strongest pick stored for it (ESPN confirmed / probable,
    or the NHL's actual starter once it has started), else last game's starter as a projection."""
    ids = [g for g in (game_id, last.game_id if last else None) if g is not None]
    picks = await load_game_starters(db, ids) if ids else pd.DataFrame()
    if game_id is not None and not picks.empty:
        mine = picks[(picks["game_id"] == game_id) & (picks["team"] == team)]
        if not mine.empty:
            best = max(mine.to_dict("records"), key=lambda r: STATUS_RANK.get(r["status"], -1))
            return int(best["player_id"]), str(best["status"])
    if last is not None:
        if not picks.empty:
            actual = picks[(picks["game_id"] == last.game_id) & (picks["team"] == team) & (picks["status"] == "actual")]
            if not actual.empty:
                return int(actual.iloc[0]["player_id"]), "projected"
        goalies = [r for r in last.lineup if r["status"] == DRESSED and r.get("position") == "G"]
        if goalies:
            return max(goalies, key=lambda r: (r.get("toi") or 0, -r["player_id"]))["player_id"], "projected"
    return None, "projected"


async def build_team_lineup(db: AsyncSession, team: str) -> TeamLineupOut:
    team = team.upper()
    next_game = await get_next_team_game(db, team)
    history = await get_recent_lineup_games(db, team, before=next_game.start_time if next_game else None,
                                            limit=HISTORY_GAMES)
    history_ids = [g.game_id for g in history]
    rows_by_game: dict[int, list[dict]] = {}
    for r in await load_lineups(db, team, history_ids + ([next_game.game_id] if next_game else [])):
        rows_by_game.setdefault(r["game_id"], []).append(r)
    with_shifts = [gid for gid in history_ids if any(r.get("toi") is not None for r in rows_by_game.get(gid, []))]
    units_by_game: dict[int, list[dict]] = {}
    for u in await load_units(db, team, with_shifts[:WINDOW + UNIT_SLACK]):
        units_by_game.setdefault(u["game_id"], []).append(u)
    games = [PastGame(gid, rows_by_game.get(gid, []), units_by_game.get(gid, [])) for gid in history_ids]

    next_rows = rows_by_game.get(next_game.game_id, []) if next_game else []
    posted = [r for r in next_rows if r["status"] == DRESSED] or None

    roster_players = list((await db.execute(select(Player).where(Player.current_team_tri_code == team))).scalars().all())
    roster = [RosterPlayer(p.id, p.position, p.shoots_catches) for p in roster_players]
    roster_ids = {p.id for p in roster_players}

    report = await load_injury_report(db)
    injury_rows = []
    if report is not None and not report.empty:
        mine = report[(report["team"] == team) | report["player_id"].isin(roster_ids)]
        injury_rows = [{k: _nan_to_none(v) for k, v in r.items()} for r in mine.to_dict("records")]
    injured = {int(r["player_id"]): r["status"] for r in injury_rows if r.get("player_id") is not None}
    listed_out = {p for p, status in injured.items() if status in OUT_STATUSES}
    since = datetime.datetime.now(datetime.timezone.utc) - RETURN_LOOKBACK
    returning = await get_recently_listed_out(db, list(roster_ids), OUT_STATUSES, since) - listed_out

    projection = project_lineup(games, roster, injured, posted, returning=returning)

    # scratches: tonight's once posted, else the last game's, for players still on the roster and not projected in
    if posted:
        scratch_game, scratch_rows, streak_games = next_game.game_id, next_rows, [PastGame(next_game.game_id, next_rows)] + games
    else:
        last = next((g for g in games if any(r["status"] == DRESSED for r in g.lineup)), None)
        scratch_game, scratch_rows, streak_games = (last.game_id, last.lineup, games) if last else (None, [], games)
    dressed = set(projection.dressed) if projection else set()
    scratched = [r["player_id"] for r in scratch_rows if r["status"] == SCRATCHED
                 and r["player_id"] not in dressed and (posted or not roster_ids or r["player_id"] in roster_ids)]

    named = set(roster_ids) | dressed | set(scratched) | set(injured)
    if projection:
        named |= set(projection.changes["out"])
    players = list((await db.execute(select(Player).where(Player.id.in_(named)))).scalars().all()) if named else []
    all_rows = [r for rows in rows_by_game.values() for r in rows]
    people = _People(players, all_rows, injured)

    goalies = []
    if projection:
        last_game = next((g for g in games if any(r["status"] == DRESSED for r in g.lineup)), None)
        starter, starter_status = await _starter(db, team, next_game.game_id if next_game else None, last_game)
        others = [g for g in projection.goalies if g != starter]
        if starter is None and others:
            starter, others = others[0], others[1:]
        if starter is not None:
            goalies.append(LineupGoalieOut(role="starter", status=starter_status, player=people.out(starter, "G")))
        if others:      # one backup, even when the announced starter isn't in the lineup we have
            goalies.append(LineupGoalieOut(role="backup", status="confirmed" if posted else "projected",
                                           player=people.out(others[0], "G")))

    updated_at = (await db.execute(select(func.max(GameLineup.fetched_at)).where(
        GameLineup.team == team, GameLineup.game_id.in_(history_ids[:1] + ([next_game.game_id] if next_game else []))))).scalar()

    return TeamLineupOut(
        team=team,
        game=LineupGameOut(id=next_game.game_id, startTime=next_game.start_time, opponent=next_game.opponent,
                           home=next_game.home, gameState=next_game.game_state) if next_game else None,
        status=projection.lineup_status if projection else "projected",
        basedOn=projection.based_on if projection else [],
        forwards=[_unit_out(u, people) for u in projection.forwards] if projection else [],
        defense=[_unit_out(u, people) for u in projection.defense] if projection else [],
        powerPlay=[_unit_out(u, people) for u in projection.power_play] if projection else [],
        penaltyKill=[_unit_out(u, people) for u in projection.penalty_kill] if projection else [],
        goalies=goalies,
        extras=[people.out(p) for p in projection.extras] if projection else [],
        changes=LineupChangesOut(playersIn=[people.out(p) for p in projection.changes["in"]],
                                 playersOut=[people.out(p) for p in projection.changes["out"]])
        if projection else LineupChangesOut(playersIn=[], playersOut=[]),
        injuries=[TeamInjuryOut(playerId=r.get("player_id"), name=r.get("full_name"), position=r.get("position"),
                                status=r["status"], injuryType=r.get("injury_type"), returnDate=r.get("return_date"),
                                comment=r.get("comment"), reportedAt=r.get("report_date"),
                                player=people.out(int(r["player_id"])) if r.get("player_id") is not None else None)
                  for r in sorted(injury_rows, key=lambda r: (r["status"] == "day_to_day", r.get("full_name") or ""))],
        scratches=[TeamScratchOut(player=people.out(p), healthy=p not in injured,
                                  gamesScratched=_scratch_streak(p, streak_games), gameId=scratch_game)
                   for p in scratched],
        injuryReportAsOf=_nan_to_none(report["fetched_at"].iloc[0]) if report is not None and not report.empty else None,
        lineupsUpdatedAt=updated_at,
    )
