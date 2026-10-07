import datetime

from sqlalchemy import func, select, union
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import GoalieGameLog, Player, PlayerPropOdds, SkaterGameLog

PLAYER_PROP_ODDS_KEY = ["game_id", "player_id", "prop_type", "line", "book"]
PLAYER_PROP_ODDS_COLUMNS = PLAYER_PROP_ODDS_KEY + [
    "espn_athlete_id", "espn_event_id", "over_price", "under_price", "open_line",
    "open_over_price", "open_under_price", "sides_inferred", "espn_last_updated",
]


def dedupe_prop_rows(rows: list[dict]) -> list[dict]:
    """One row per primary key (ON CONFLICT cannot touch the same row twice in one statement); last wins."""
    return list({tuple(row[c] for c in PLAYER_PROP_ODDS_KEY): row for row in rows}.values())


def player_prop_odds_upsert_stmt(batch: list[dict]):
    """INSERT ... ON CONFLICT (game_id, player_id, prop_type, line, book) DO UPDATE.

    A missing opening price never overwrites a stored one, so the open captured on an
    earlier run survives a later snapshot that lacks it."""
    now = datetime.datetime.now(datetime.timezone.utc)
    stmt = insert(PlayerPropOdds).values([{**{c: row.get(c) for c in PLAYER_PROP_ODDS_COLUMNS}, "last_updated": now} for row in batch])
    keep_if_null = {"open_line", "open_over_price", "open_under_price"}
    set_ = {}
    for c in PLAYER_PROP_ODDS_COLUMNS:
        if c in PLAYER_PROP_ODDS_KEY:
            continue
        excluded = stmt.excluded[c]
        if c in keep_if_null:
            set_[c] = func.coalesce(excluded, getattr(PlayerPropOdds, c))
        else:
            set_[c] = excluded
    set_["last_updated"] = now
    return stmt.on_conflict_do_update(index_elements=PLAYER_PROP_ODDS_KEY, set_=set_)


async def upsert_player_prop_odds(db: AsyncSession, rows: list[dict]):
    """Upserts player prop market rows (see external.espn.props / app.schedules.fetch_player_prop_odds_for_range)."""
    rows = dedupe_prop_rows(rows)
    for i in range(0, len(rows), 1000):
        await db.execute(player_prop_odds_upsert_stmt(rows[i : i + 1000]))
    await db.commit()


async def get_player_prop_odds(db: AsyncSession, game_ids: list[int] | None = None,
                               player_id: int | None = None) -> list[PlayerPropOdds]:
    query = select(PlayerPropOdds).order_by(PlayerPropOdds.game_id, PlayerPropOdds.player_id, PlayerPropOdds.prop_type, PlayerPropOdds.line)
    if game_ids is not None:
        query = query.where(PlayerPropOdds.game_id.in_(game_ids))
    if player_id is not None:
        query = query.where(PlayerPropOdds.player_id == player_id)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_known_athlete_ids(db: AsyncSession) -> dict[int, int]:
    """ESPN athlete id -> NHL player id pairs already stored (the persistent mapping cache)."""
    result = await db.execute(select(PlayerPropOdds.espn_athlete_id, PlayerPropOdds.player_id).distinct())
    return {athlete_id: player_id for athlete_id, player_id in result.all()}


async def get_player_match_data(db: AsyncSession, min_season: int) -> tuple[list[dict], set, set]:
    """Players plus game-log evidence for ESPN athlete matching (external.espn.player_ids):
    (players, {(player_id, season, team)}, {(game_id, player_id)}) for logs from `min_season` on."""
    players = [
        {"id": p.id, "first_name": p.first_name, "last_name": p.last_name, "position": p.position,
         "current_team": p.current_team_tri_code}
        for p in (await db.execute(select(Player))).scalars().all()
    ]
    logs = union(
        select(SkaterGameLog.game_id, SkaterGameLog.player_id, SkaterGameLog.season, SkaterGameLog.player_team_tricode)
        .where(SkaterGameLog.season >= min_season),
        select(GoalieGameLog.game_id, GoalieGameLog.player_id, GoalieGameLog.season, GoalieGameLog.player_team_tricode)
        .where(GoalieGameLog.season >= min_season),
    )
    team_seasons, game_players = set(), set()
    for game_id, player_id, season, team in (await db.execute(logs)).all():
        team_seasons.add((player_id, season, team))
        game_players.add((game_id, player_id))
    return players, team_seasons, game_players
