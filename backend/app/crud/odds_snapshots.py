"""Append-only odds price path (game_odds_snapshots / player_prop_snapshots).

Every ESPN fetch appends one row per game (and per prop market) stamped with the fetch time, so the price path
survives the overwrite of game_odds / player_prop_odds. Rules that keep in-game prices out:

* before puck drop (captured_at < games.start_time) the fetched price is a pre-game snapshot;
* once the game is final (games.game_state OFF/FINAL), ESPN's stored price is the one frozen at puck drop, so the
  first fetch after the final writes it once as the `is_closing` snapshot;
* anything in between (started, not final; or postponed/stale) is skipped.
ESPN's in-game "live" providers are already dropped upstream (external.espn.odds.consensus / props.prop_providers).
"""
from __future__ import annotations

import datetime
from collections import defaultdict

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Games, GameOddsSnapshot, PlayerPropSnapshot
from .games import FINISHED_GAME_STATES

GAME_SOURCE = "espn"


def as_utc(ts: datetime.datetime | None) -> datetime.datetime | None:
    """Timezone-aware UTC (SQLite hands back naive datetimes)."""
    if ts is None:
        return None
    return ts.replace(tzinfo=datetime.timezone.utc) if ts.tzinfo is None else ts.astimezone(datetime.timezone.utc)


def snapshot_phase(start_time: datetime.datetime | None, game_state: str | None, now: datetime.datetime) -> str | None:
    """"pregame", "closing" or None (in progress / unknown game: never record)."""
    if start_time is None:
        return None
    if game_state in FINISHED_GAME_STATES:
        return "closing"
    if as_utc(now) < as_utc(start_time):
        return "pregame"
    return None


def _round(price: float | None) -> float | None:
    """Consensus prices are medians on the decimal scale; drop the float noise (-161.99999 -> -162)."""
    return None if price is None else round(price, 2)


async def _game_info(db: AsyncSession, game_ids: set[int]) -> dict[int, tuple]:
    if not game_ids:
        return {}
    result = await db.execute(select(Games.id, Games.start_time, Games.game_state).where(Games.id.in_(game_ids)))
    return {gid: (start, state) for gid, start, state in result.all()}


async def _games_with_closing(db: AsyncSession, model, game_ids: set[int]) -> set[int]:
    if not game_ids:
        return set()
    result = await db.execute(select(model.game_id).where(model.game_id.in_(game_ids), model.is_closing.is_(True)).distinct())
    return set(result.scalars().all())


async def _phases(db: AsyncSession, model, game_ids: set[int], now: datetime.datetime) -> dict[int, str]:
    """game_id -> phase to record now (games already holding a closing snapshot get none)."""
    info = await _game_info(db, game_ids)
    phases = {gid: snapshot_phase(start, state, now) for gid, (start, state) in info.items()}
    closed = await _games_with_closing(db, model, {g for g, p in phases.items() if p == "closing"})
    return {gid: p for gid, p in phases.items() if p is not None and gid not in closed}


async def insert_game_odds_snapshots(db: AsyncSession, rows: list[dict], captured_at: datetime.datetime | None = None) -> int:
    """Appends game odds rows (external.espn.game_odds.build_game_odds_rows) as snapshots. Returns rows written."""
    now = as_utc(captured_at) or datetime.datetime.now(datetime.timezone.utc)
    phases = await _phases(db, GameOddsSnapshot, {int(r["game_id"]) for r in rows}, now)
    values, seen = [], set()
    for r in rows:
        gid = int(r["game_id"])
        if gid not in phases or gid in seen:
            continue
        seen.add(gid)
        values.append({
            "game_id": gid, "captured_at": now, "source": GAME_SOURCE, "is_closing": phases[gid] == "closing",
            "home_moneyline": _round(r.get("home_moneyline")), "away_moneyline": _round(r.get("away_moneyline")),
            "home_prob_novig": r.get("home_prob_novig"), "total_line": r.get("total_line"),
            "over_price": _round(r.get("total_over_price")), "under_price": _round(r.get("total_under_price")),
            "n_books": r.get("n_books"), "books": r.get("books"),
        })
    if values:
        await db.execute(insert(GameOddsSnapshot), values)
        await db.commit()
    return len(values)


async def insert_player_prop_snapshots(db: AsyncSession, rows: list[dict], captured_at: datetime.datetime | None = None) -> int:
    """Appends player prop market rows (external.espn.props.build_player_prop_rows) as snapshots."""
    now = as_utc(captured_at) or datetime.datetime.now(datetime.timezone.utc)
    phases = await _phases(db, PlayerPropSnapshot, {int(r["game_id"]) for r in rows}, now)
    values = {}
    for r in rows:
        gid = int(r["game_id"])
        if gid not in phases:
            continue
        key = (gid, r["player_id"], r["prop_type"], float(r["line"]), r["book"])
        values[key] = {
            "game_id": gid, "player_id": r["player_id"], "prop_type": r["prop_type"], "line": float(r["line"]),
            "book": r["book"], "captured_at": now, "is_closing": phases[gid] == "closing",
            "over_price": r.get("over_price"), "under_price": r.get("under_price"),
            "sides_inferred": bool(r.get("sides_inferred")), "espn_last_updated": r.get("espn_last_updated"),
        }
    batch = list(values.values())
    for i in range(0, len(batch), 2000):
        await db.execute(insert(PlayerPropSnapshot), batch[i:i + 2000])
    if batch:
        await db.commit()
    return len(batch)


# ---------- reads ----------

async def latest_game_snapshots(db: AsyncSession, game_ids: list[int], as_of: datetime.datetime) -> dict[int, GameOddsSnapshot]:
    """Most recent pre-game snapshot captured at or before `as_of`, per game."""
    if not game_ids:
        return {}
    result = await db.execute(
        select(GameOddsSnapshot).where(GameOddsSnapshot.game_id.in_(game_ids), GameOddsSnapshot.is_closing.is_(False))
        .order_by(GameOddsSnapshot.captured_at))
    out = {}
    for snap in result.scalars().all():
        if as_utc(snap.captured_at) <= as_utc(as_of):
            out[snap.game_id] = snap
    return out


async def closing_game_snapshots(db: AsyncSession, game_ids: list[int]) -> dict[int, GameOddsSnapshot]:
    """The closing snapshot per game: the frozen-at-puck-drop row if captured, else the last pre-game snapshot
    before the start time (only for games with a known start)."""
    if not game_ids:
        return {}
    starts = {gid: start for gid, (start, _) in (await _game_info(db, set(game_ids))).items()}
    result = await db.execute(select(GameOddsSnapshot).where(GameOddsSnapshot.game_id.in_(game_ids))
                              .order_by(GameOddsSnapshot.captured_at))
    closing, last_pre = {}, {}
    for snap in result.scalars().all():
        if snap.is_closing:
            closing.setdefault(snap.game_id, snap)
        elif snap.game_id in starts and as_utc(snap.captured_at) < as_utc(starts[snap.game_id]):
            last_pre[snap.game_id] = snap
    return {**last_pre, **closing}


async def _prop_rows_at(db: AsyncSession, game_ids: list[int], pick) -> dict[int, list[PlayerPropSnapshot]]:
    """Groups prop snapshots by game and capture time, then keeps the capture `pick(game_id, captures)` chooses."""
    if not game_ids:
        return {}
    result = await db.execute(select(PlayerPropSnapshot).where(PlayerPropSnapshot.game_id.in_(game_ids)))
    by_game: dict[int, dict] = defaultdict(lambda: defaultdict(list))
    for snap in result.scalars().all():
        by_game[snap.game_id][(as_utc(snap.captured_at), snap.is_closing)].append(snap)
    out = {}
    for gid, captures in by_game.items():
        key = pick(gid, sorted(captures))
        if key is not None:
            out[gid] = captures[key]
    return out


async def latest_prop_snapshots(db: AsyncSession, game_ids: list[int], as_of: datetime.datetime) -> dict[int, list[PlayerPropSnapshot]]:
    """Every market of the most recent pre-game prop fetch at or before `as_of`, per game."""
    as_of = as_utc(as_of)
    def pick(_gid, keys):
        pre = [k for k in keys if not k[1] and k[0] <= as_of]
        return pre[-1] if pre else None
    return await _prop_rows_at(db, game_ids, pick)


async def closing_prop_snapshots(db: AsyncSession, game_ids: list[int]) -> dict[int, list[PlayerPropSnapshot]]:
    """Every market of the closing prop capture per game (frozen row if captured, else last fetch before the start)."""
    starts = {gid: as_utc(start) for gid, (start, _) in (await _game_info(db, set(game_ids))).items()}
    def pick(gid, keys):
        closing = [k for k in keys if k[1]]
        if closing:
            return closing[0]
        pre = [k for k in keys if gid in starts and k[0] < starts[gid]]
        return pre[-1] if pre else None
    return await _prop_rows_at(db, game_ids, pick)
