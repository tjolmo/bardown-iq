"""game_lineups / game_units: who dressed, who was scratched and how teams deployed their players (see
app/deployment.py). Writes replace a game's rows (delete, then insert) so a re-fetch never leaves a stale row, and
work on any dialect."""
import datetime
from dataclasses import dataclass

from sqlalchemy import and_, delete, func, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deployment import TeamDeployment, unit_rows
from ..models import GameLineup, GameUnit, Games
from .games import FINISHED_GAME_STATES

DRESSED, SCRATCHED = "dressed", "scratched"
LINEUP_COLUMNS = ["game_id", "team", "player_id", "status", "position", "sweater_number", "first_name", "last_name",
                  "toi", "toi_ev", "toi_pp", "toi_pk", "faceoffs"]


def lineup_rows(data, deployments: dict[str, TeamDeployment] | None = None) -> dict[str, list[dict]]:
    """team -> game_lineups rows for one game's fetched data (external.nhl.lineups.GameLineupData). Only teams whose
    dressed players are posted get rows; ice time is filled from `deployments` (None before the shift chart)."""
    by_team: dict[str, list[dict]] = {}
    for spot in data.roster_spots or []:
        dep = (deployments or {}).get(spot.team)
        toi = {}
        if dep is not None:
            toi = {"toi": dep.toi.get(spot.player_id, 0), "toi_ev": dep.toi_ev.get(spot.player_id, 0),
                   "toi_pp": dep.toi_pp.get(spot.player_id, 0), "toi_pk": dep.toi_pk.get(spot.player_id, 0)}
        by_team.setdefault(spot.team, []).append({
            "game_id": data.game_id, "team": spot.team, "player_id": spot.player_id, "status": DRESSED,
            "position": spot.position, "sweater_number": spot.sweater_number, "first_name": spot.first_name,
            "last_name": spot.last_name, "toi": toi.get("toi"), "toi_ev": toi.get("toi_ev"),
            "toi_pp": toi.get("toi_pp"), "toi_pk": toi.get("toi_pk"),
            "faceoffs": data.faceoffs.get(spot.player_id, 0) if dep is not None else None})
    for s in data.scratches or []:
        rows = by_team.get(s.team)
        if rows is None or any(r["player_id"] == s.player_id for r in rows):
            continue
        rows.append({"game_id": data.game_id, "team": s.team, "player_id": s.player_id, "status": SCRATCHED,
                     "position": None, "sweater_number": None, "first_name": s.first_name, "last_name": s.last_name,
                     "toi": None, "toi_ev": None, "toi_pp": None, "toi_pk": None, "faceoffs": None})
    return by_team


async def store_game_lineup(db: AsyncSession, data, deployments: dict[str, TeamDeployment] | None = None,
                            fetched_at: datetime.datetime | None = None) -> int:
    """Replaces the stored lineups of each team whose dressed players are in `data`, and, with `deployments`, the
    game's units. A fetch that found nothing (lineups not posted yet) changes nothing. Returns lineup rows written."""
    fetched_at = fetched_at or datetime.datetime.now(datetime.timezone.utc)
    by_team = lineup_rows(data, deployments)
    written = 0
    for team, rows in by_team.items():
        await db.execute(delete(GameLineup).where(GameLineup.game_id == data.game_id, GameLineup.team == team))
        await db.execute(insert(GameLineup), [{**r, "fetched_at": fetched_at} for r in rows])
        written += len(rows)
    if deployments is not None:
        units = unit_rows(data.game_id, deployments)
        await db.execute(delete(GameUnit).where(GameUnit.game_id == data.game_id))
        if units:
            await db.execute(insert(GameUnit), units)
    await db.commit()
    return written


async def get_games_missing_deployment(db: AsyncSession, min_season: int, max_season: int | None = None,
                                       recheck_days: float | None = 3, started_after: datetime.datetime | None = None,
                                       limit: int | None = None, now: datetime.datetime | None = None) -> list[Games]:
    """Finished regular-season and playoff games of seasons `min_season`..`max_season` (start years), oldest first,
    whose lineups have no ice time yet (never fetched, or fetched before the shift chart was in). A game fetched
    without one stops being retried `recheck_days` after it started (None: always retried, as the backfill does);
    `started_after` keeps only recent games."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    have = select(GameLineup.game_id).where(GameLineup.toi.is_not(None)).distinct()
    game_type = Games.id // 10000 % 100
    conds = [Games.game_state.in_(FINISHED_GAME_STATES), game_type.in_((2, 3)), Games.season >= min_season * 10000,
             Games.id.not_in(have)]
    if max_season is not None:
        conds.append(Games.season < (max_season + 1) * 10000)
    if recheck_days is not None:
        fetched = select(GameLineup.game_id).distinct()
        conds.append(or_(Games.id.not_in(fetched), Games.start_time >= now - datetime.timedelta(days=recheck_days)))
    if started_after is not None:
        conds.append(Games.start_time >= started_after)
    stmt = select(Games).where(and_(*conds)).order_by(Games.start_time, Games.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def get_games_awaiting_lineups(db: AsyncSession, now: datetime.datetime | None = None,
                                     lead: datetime.timedelta = datetime.timedelta(minutes=90),
                                     max_age: datetime.timedelta = datetime.timedelta(hours=8)) -> list[Games]:
    """Unfinished games starting within `lead` (or started up to `max_age` ago) without both teams' lineups stored:
    the NHL posts lineups and scratches shortly before puck drop."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    posted = (select(GameLineup.game_id).where(GameLineup.status == DRESSED)
              .group_by(GameLineup.game_id).having(func.count(func.distinct(GameLineup.team)) >= 2))
    stmt = select(Games).where(Games.start_time <= now + lead, Games.start_time >= now - max_age,
                               Games.game_state.not_in(FINISHED_GAME_STATES), Games.id.not_in(posted))
    return list((await db.execute(stmt.order_by(Games.start_time))).scalars().all())


@dataclass
class TeamGame:
    game_id: int
    start_time: datetime.datetime
    opponent: str
    home: bool
    game_state: str


def _team_game(g: Games, team: str) -> TeamGame:
    home = g.home_team_tri_code == team
    return TeamGame(game_id=g.id, start_time=g.start_time, home=home, game_state=g.game_state,
                    opponent=g.away_team_tri_code if home else g.home_team_tri_code)


async def get_recent_lineup_games(db: AsyncSession, team: str, before: datetime.datetime | None = None,
                                  limit: int = 10) -> list[TeamGame]:
    """The team's most recent games with a stored lineup, newest first (started before `before` when given)."""
    stmt = (select(Games).join(GameLineup, and_(GameLineup.game_id == Games.id, GameLineup.team == team))
            .where(GameLineup.status == DRESSED).distinct())
    if before is not None:
        stmt = stmt.where(Games.start_time < before)
    stmt = stmt.order_by(Games.start_time.desc()).limit(limit)
    return [_team_game(g, team) for g in (await db.execute(stmt)).scalars().all()]


async def get_next_team_game(db: AsyncSession, team: str) -> TeamGame | None:
    """The team's next game that isn't over (a game under way counts), by start time."""
    stmt = (select(Games).where(or_(Games.home_team_tri_code == team, Games.away_team_tri_code == team),
                                Games.game_state.not_in(FINISHED_GAME_STATES), (Games.id // 10000 % 100).in_((2, 3)))
            .order_by(Games.start_time).limit(1))
    game = (await db.execute(stmt)).scalar_one_or_none()
    return _team_game(game, team) if game else None


async def load_lineups(db: AsyncSession, team: str, game_ids: list[int]) -> list[dict]:
    if not game_ids:
        return []
    stmt = select(*[getattr(GameLineup, c) for c in LINEUP_COLUMNS]).where(
        GameLineup.team == team, GameLineup.game_id.in_(game_ids))
    return [dict(r) for r in (await db.execute(stmt)).mappings().all()]


async def load_units(db: AsyncSession, team: str, game_ids: list[int]) -> list[dict]:
    if not game_ids:
        return []
    stmt = select(GameUnit.game_id, GameUnit.situation, GameUnit.unit, GameUnit.seconds).where(
        GameUnit.team == team, GameUnit.game_id.in_(game_ids))
    return [dict(r) for r in (await db.execute(stmt)).mappings().all()]
