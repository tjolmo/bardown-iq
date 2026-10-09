"""Players with edge: every player with a prop on the next slate where the model's expected return at the shown price
is positive for at least one side (the same model_prob/edge the player page shows).

Pricing a slate is one model prediction per player with props (~37 a game, ~0.15 s each), so a full slate takes most
of a minute. The board is cached per game day: a request gets the cached board straight away and, once it's older
than BOARD_TTL_SECONDS or the models were retrained, starts a rebuild in the background. Only the first request of a
game day (or the pipelines' warm step, which runs after each props fetch) waits for a build.
"""
from __future__ import annotations

import asyncio
import datetime
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.games import FINISHED_GAME_STATES
from app.crud.props import get_player_prop_board
from app.models import Games, Player, PlayerPropOdds, Props
from app.schemas.player import PlayerPropOut
from predictions.config import GOALIE_BUNDLE, SKATER_BUNDLE
from predictions.predict import predict_goalie, predict_skater, prop_dispersion, prop_probability

BOARD_TTL_SECONDS = 600

_cache: dict[int, dict] = {}          # game day -> {"board", "built_at", "models"}
_build_lock = asyncio.Lock()
_refresh: asyncio.Task | None = None


def american_to_decimal(odds: float) -> float:
    return 1 + odds / 100 if odds > 0 else 1 + 100 / abs(odds)


async def price_props(db: AsyncSession, player: Player | None, props: list[PlayerPropOut], game) -> dict | None:
    """Fills model_prob and edge (expected return per unit at the shown odds) on `props` in place, for the player's
    prediction in `game`. Returns the prediction (None when the player isn't on either team or has no history).
    Raises FileNotFoundError / LookupError before the models are trained."""
    team = player.current_team_tri_code if player else None
    if game is None or team not in (game.home_team_tri_code, game.away_team_tri_code):
        return None
    predict = predict_goalie if player.position == "G" else predict_skater
    expected = await predict(db, player.id, team, game)
    if not expected:
        return None
    alphas = prop_dispersion()
    for prop in props:
        prop.model_prob = prop_probability(expected, prop.prop_type, prop.line, prop.over_under, alphas)
        if prop.model_prob is not None:
            prop.edge = round(prop.model_prob * american_to_decimal(prop.odds) - 1, 4)
            prop.model_prob = round(prop.model_prob, 4)
    return expected


def _models_key() -> tuple:
    return tuple(p.stat().st_mtime if p.exists() else None for p in (SKATER_BUNDLE, GOALIE_BUNDLE))


async def next_slate(db: AsyncSession, now: datetime.datetime | None = None) -> tuple[int | None, list[Games]]:
    """The earliest game day with a game that hasn't started, and that day's unstarted games (props on a game under
    way are live prices the pre-game model can't be compared with)."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    upcoming = (await db.execute(select(Games).where(Games.start_time > now,
                                                     Games.game_state.not_in(FINISHED_GAME_STATES))
                                 .order_by(Games.date, Games.start_time))).scalars().all()
    upcoming = [g for g in upcoming if g.id // 10_000 % 100 in (2, 3)]
    if not upcoming:
        return None, []
    day = upcoming[0].date
    return day, [g for g in upcoming if g.date == day]


async def build_board(db: AsyncSession, now: datetime.datetime | None = None) -> dict:
    """Prices every player with props on the next slate. Players are kept when at least one side has a positive
    edge; each keeps all of his priced props so the page can show the rest on demand."""
    day, games = await next_slate(db, now)
    board = {"game_date": day, "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
             "players_priced": 0, "players": []}
    if not games:
        return board
    by_id = {g.id: g for g in games}
    player_ids = set((await db.execute(select(Props.player_id).where(Props.game_id.in_(by_id)))).scalars())
    player_ids |= set((await db.execute(select(PlayerPropOdds.player_id)
                                        .where(PlayerPropOdds.game_id.in_(by_id)))).scalars())
    players = {p.id: p for p in (await db.execute(select(Player).where(Player.id.in_(player_ids)))).scalars()}
    for pid in sorted(player_ids):
        player = players.get(pid)
        if player is None:
            continue
        props = [p for p in await get_player_prop_board(db, pid) if p.game_id in by_id]
        if not props:
            continue
        game = by_id[props[0].game_id]
        try:
            expected = await price_props(db, player, props, game)
        except (FileNotFoundError, LookupError):
            return board    # no models yet: nothing to price
        except Exception as e:
            print(f"Edge board: pricing player {pid} failed: {e!r}")
            continue
        if expected is None:
            continue
        # a goalie's numbers assume he starts; a known backup's saves props would show false edges
        if player.position == "G" and expected.get("starting") is False:
            continue
        board["players_priced"] += 1
        edges = [p.edge for p in props if p.edge is not None]
        if not edges or max(edges) <= 0:
            continue
        team = player.current_team_tri_code
        home = team == game.home_team_tri_code
        board["players"].append({
            "player_id": pid, "first_name": player.first_name, "last_name": player.last_name,
            "headshot": player.headshot, "position": player.position, "team": team,
            "opponent": game.away_team_tri_code if home else game.home_team_tri_code, "home": home,
            "game_id": game.id, "start_time": game.start_time.isoformat() if game.start_time else None,
            "starter_status": expected.get("starter_status") if player.position == "G" else None,
            "best_edge": max(edges),
            "props": sorted(props, key=lambda p: -(p.edge if p.edge is not None else -9)),
        })
    board["players"].sort(key=lambda p: -p["best_edge"])
    return board


def _fresh(day: int | None) -> dict | None:
    entry = _cache.get(day) if day is not None else None
    if entry and time.monotonic() - entry["built_at"] <= BOARD_TTL_SECONDS and entry["models"] == _models_key():
        return entry
    return None


async def _rebuild(session_factory, day: int | None = None, force: bool = False) -> dict:
    async with _build_lock:
        # a request that waited on a build already running gets that build instead of starting another
        if not force and (entry := _fresh(day)):
            return entry["board"]
        async with session_factory() as db:
            models = _models_key()
            board = await build_board(db)
        if board["game_date"] is not None:
            _cache[board["game_date"]] = {"board": board, "built_at": time.monotonic(), "models": models}
        for day in [d for d in _cache if board["game_date"] is not None and d < board["game_date"]]:
            del _cache[day]
        return board


async def get_board(db: AsyncSession, session_factory) -> dict:
    """The cached board for the next slate, refreshed in the background when stale; built inline on a miss."""
    global _refresh
    day, _ = await next_slate(db)
    entry = _cache.get(day) if day is not None else None
    if entry is None:
        return await _rebuild(session_factory, day)
    stale = time.monotonic() - entry["built_at"] > BOARD_TTL_SECONDS or entry["models"] != _models_key()
    if stale and not _build_lock.locked() and (_refresh is None or _refresh.done()):
        _refresh = asyncio.create_task(_rebuild(session_factory))
    return {**entry["board"], "refreshing": stale}


async def warm_board(session_factory) -> None:
    """Rebuilds the board now (pipelines call this after fetching props)."""
    board = await _rebuild(session_factory, force=True)
    print(f"Edge board: {len(board['players'])} of {board['players_priced']} priced players have an edge "
          f"(game day {board['game_date']})")
