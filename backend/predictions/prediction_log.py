"""Forward test of the frozen models: log pre-game predictions with the market price, score them after the games.

RESULTS_v3.md / RESULTS_props_v2.md conclude that backtests can't show an edge against the close; the honest test is
a frozen model run forward, tracked with closing-line value. This module is that loop:

* `log_predictions` (pre-game log, ~30 minutes before each puck drop): for every game today that hasn't started, the team win probability and
  every player's expected counts (skater and goalie bundles), with the latest pre-game market snapshot
  (app.crud.odds_snapshots). A player stat takes ESPN's line when ESPN has a two-sided one, else the consensus
  across PropLine's books (prop_quotes; the Odds API before Oct 2026), and records which (`market_source`). Insert-only; a
  (game, model_version) already logged is skipped.
* `score_predictions` (nightly pipeline): joins logged rows with results and the closing snapshot and writes
  prediction_scores once per logged row: log loss (team; P(over) for players), Poisson deviance (players),
  market log loss at log time and at the close (from the same feed as the logged line), CLV in vig-free probability
  (close minus logged market prob, signed toward the model's side) and, for picks clearing a frozen edge threshold,
  price CLV (decimal logged / decimal close - 1) and flat-stake profit.
* `model_report`: aggregates prediction_scores (calibration buckets, CLV, ROI, per line feed) and the line coverage
  of the logged player rows for GET /admin/model-report.

CLI (inside the backend container):
    python -m predictions.prediction_log log [--date YYYYMMDD] [--run-id ID]
    python -m predictions.prediction_log score
    python -m predictions.prediction_log report [--model-version V] [--start YYYYMMDD] [--end YYYYMMDD]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import hashlib
import json
import math
from types import SimpleNamespace
import statistics
from collections import Counter, defaultdict

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.games import FINISHED_GAME_STATES
from external.propline.books import CONSENSUS_BOOKS
from app.crud.prop_quotes import get_quotes_for_games
from app.crud.odds_snapshots import (as_utc, closing_game_snapshots, closing_prop_snapshots, latest_game_snapshots,
                                     latest_prop_snapshots)
from app.models import (GoalieGameLog, Games, Player, PlayerPredictionLog, PredictionLog, PredictionScore,
                        SkaterGameLog)
from .config import GOALIE_BUNDLE, METRICS_PATH, SKATER_BUNDLE, TEAM_BUNDLE

# frozen before the forward test starts: a pick needs the model's side to beat the vig-free market by this much
EDGE_THRESHOLD = 0.02
DEVIG_METHOD = "multiplicative"
# a game's closing snapshot can be missing (fetch failed); after this many days score without it
CLOSE_WAIT_DAYS = 2
# player rows whose game has no logs this many days after it was played are marked no_result
RESULT_WAIT_DAYS = 5
# model stat -> prop_probability's market key, which is also the prop_quotes market the fallback line is read from
# (neither PropLine nor the Odds API has an NHL hits market); pp_points stays unpriced (5-on-4 only, books settle all PP strengths)
PROP_KEYS = {"goals": "player_goals", "assists": "player_assists", "points": "player_points",
             "shots_on_goal": "player_shots_on_goal", "hits": "player_hits", "blocked_shots": "player_blocked_shots",
             "saves": "player_total_saves"}
EPS = 1e-6


# ---------- model version ----------

_version_cache: dict = {}

def model_version() -> str:
    """'<trained_at>-<sha1 of the three bundles>'. The hash changes whenever any bundle is rewritten."""
    paths = [p for p in (TEAM_BUNDLE, SKATER_BUNDLE, GOALIE_BUNDLE) if p.exists()]
    key = tuple((str(p), p.stat().st_mtime, p.stat().st_size) for p in paths)
    if _version_cache.get("key") != key:
        h = hashlib.sha1()
        for p in paths:
            h.update(p.name.encode())
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
        trained_at = "untrained"
        if METRICS_PATH.exists():
            trained_at = json.loads(METRICS_PATH.read_text()).get("trained_at", trained_at)
        _version_cache.update(key=key, value=f"{trained_at[:19]}-{h.hexdigest()[:10]}")
    return _version_cache["value"]


# ---------- odds math ----------

def american_to_decimal(american: float | None) -> float | None:
    if american is None or abs(american) < 100:
        return None
    return 1 + (american / 100 if american > 0 else 100 / -american)


def devig_pair(over: float | None, under: float | None) -> float | None:
    """Vig-free probability of the first side of a two-way American price pair."""
    if american_to_decimal(over) is None or american_to_decimal(under) is None:
        return None
    from .vig import devig_two_way
    return float(devig_two_way([over], [under], DEVIG_METHOD)[0])


def median_american(prices) -> float | None:
    decimals = [d for d in (american_to_decimal(p) for p in prices) if d is not None]
    if not decimals:
        return None
    d = statistics.median(decimals)
    return round((d - 1) * 100 if d >= 2 else -100 / (d - 1), 2)


def prop_consensus(rows, line: float) -> dict | None:
    """Median prices and vig-free P(over) across books quoting both sides of `line`."""
    two_sided = [r for r in rows if float(_get(r, "line")) == float(line)
                 and american_to_decimal(_get(r, "over_price")) and american_to_decimal(_get(r, "under_price"))]
    if not two_sided:
        return None
    probs = [devig_pair(_get(r, "over_price"), _get(r, "under_price")) for r in two_sided]
    return {"line": float(line), "over_price": median_american(_get(r, "over_price") for r in two_sided),
            "under_price": median_american(_get(r, "under_price") for r in two_sided),
            "p_over": statistics.median(probs), "n_books": len(two_sided)}


def main_prop_market(rows) -> dict | None:
    """The market's main line for one player and prop type: the two-sided line most books quote, ties broken by the
    line priced closest to 50/50. One-sided markets (milestones, anytime goal) have no vig-free price and are skipped."""
    lines = {float(_get(r, "line")) for r in rows}
    markets = [m for m in (prop_consensus(rows, line) for line in lines) if m]
    if not markets:
        return None
    return max(markets, key=lambda m: (m["n_books"], -abs(m["p_over"] - 0.5)))


def _get(row, key):
    return row[key] if isinstance(row, dict) else getattr(row, key)


def quote_book_rows(quotes, as_of: datetime.datetime) -> dict[tuple, list[dict]]:
    """Multi-book quotes (prop_quotes rows: one book, one side) as they stood at `as_of`, paired into two-sided
    book rows shaped like prop snapshots, keyed (game_id, player_id, model stat). PropLine rows count only from the
    consensus books (the exchanges and Bovada are stored but kept out); each row carries its `provider`.

    A quote row only keeps its first and latest fetch, so per game the price path is rebuilt from the latest fetch
    at or before `as_of`: quotes seen in it (first_seen <= fetch <= last_seen) are live, at their latest price if
    last_seen <= as_of, else at their first price. Quotes a book pulled before that fetch (last_seen older) are
    dropped. At live log time `as_of` is after every fetch, so this is simply the latest fetch."""
    as_of = as_utc(as_of)
    stats = {key: stat for stat, key in PROP_KEYS.items()}
    by_game = defaultdict(list)
    for q in quotes:
        provider = _provider(q)
        if provider == "propline" and _get(q, "bookmaker") not in CONSENSUS_BOOKS:
            continue
        if _get(q, "prop_type") in stats and as_utc(_get(q, "first_seen")) <= as_of:
            by_game[_get(q, "game_id")].append(q)
    out: dict[tuple, dict] = {}
    for gid, qs in by_game.items():
        seen = [as_utc(_get(q, "last_seen")) for q in qs] + [as_utc(_get(q, "first_seen")) for q in qs]
        fetch = max(t for t in seen if t <= as_of)
        for q in qs:
            first, last = as_utc(_get(q, "first_seen")), as_utc(_get(q, "last_seen"))
            if last < fetch:
                continue
            side = str(_get(q, "over_under")).lower()
            if side not in ("over", "under"):
                continue   # one-sided (anytime goal "Yes"): no vig-free price
            price, captured = (_get(q, "odds"), last) if last <= as_of else (_get(q, "first_odds"), first)
            stat = stats[_get(q, "prop_type")]
            key = (gid, _get(q, "player_id"), stat, float(_get(q, "line")), _get(q, "bookmaker"))
            row = out.setdefault(key, {"game_id": gid, "player_id": key[1], "prop_type": stat, "line": key[3],
                                       "book": key[4], "over_price": None, "under_price": None,
                                       "captured_at": captured, "provider": _provider(q)})
            row[f"{side}_price"] = price
            row["captured_at"] = max(row["captured_at"], captured)
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in out.values():
        grouped[(row["game_id"], row["player_id"], row["prop_type"])].append(row)
    return dict(grouped)


def _provider(q) -> str:
    """Feed of a prop_quotes row: rows stored before the provider column existed came from the Odds API."""
    provider = q.get("provider") if isinstance(q, dict) else getattr(q, "provider", None)
    return provider or "odds_api"


def pick_market(espn_rows, quote_rows) -> tuple[dict | None, str | None, datetime.datetime | None]:
    """(main market, source, captured_at) for one player and stat: ESPN's line when it has a two-sided one, else
    the consensus of the multi-book quotes ("propline", or "odds_api" for older games; most player rows have no
    ESPN line since DraftKings replaced ESPN BET), else nothing."""
    m = main_prop_market(espn_rows) if espn_rows else None
    if m:
        return m, "espn", _get(espn_rows[0], "captured_at")
    m = main_prop_market(quote_rows) if quote_rows else None
    if m:
        at_line = [r for r in quote_rows if float(r["line"]) == m["line"]]
        newest = max(at_line, key=lambda r: r["captured_at"])
        return m, newest.get("provider", "odds_api"), newest["captured_at"]
    return None, None, None


# ---------- scoring math ----------

def log_loss(p: float | None, y: int | None) -> float | None:
    if p is None or y is None:
        return None
    p = min(max(p, EPS), 1 - EPS)
    return -math.log(p if y else 1 - p)


def poisson_deviance(y: float | None, mu: float | None) -> float | None:
    if y is None or mu is None:
        return None
    mu = max(mu, EPS)
    return 2 * ((y * math.log(y / mu) if y > 0 else 0.0) - (y - mu))


def clv_prob(model_p: float | None, logged_p: float | None, close_p: float | None) -> float | None:
    """How far the vig-free market moved toward the model's side between the log and the close (positive = toward).
    Probabilities are of the same event (home win / over)."""
    if model_p is None or logged_p is None or close_p is None:
        return None
    side = 1 if model_p > logged_p else -1 if model_p < logged_p else 0
    return side * (close_p - logged_p)


def price_clv(logged_price: float | None, close_price: float | None) -> float | None:
    """Decimal odds taken / closing decimal odds of the same side, minus 1 (positive = beat the close)."""
    a, b = american_to_decimal(logged_price), american_to_decimal(close_price)
    if a is None or b is None:
        return None
    return a / b - 1


def pick_side(p_first: float | None, market_first: float | None, sides: tuple[str, str],
              p_second: float | None = None, threshold: float = EDGE_THRESHOLD) -> tuple[str | None, float | None]:
    """(side, edge) of a would-bet pick, or (None, None). `p_second` is the model's probability of the other side
    when it isn't 1 - p_first (whole-number prop lines can push)."""
    if p_first is None or market_first is None:
        return None, None
    p_second = 1 - p_first if p_second is None else p_second
    edges = {sides[0]: p_first - market_first, sides[1]: p_second - (1 - market_first)}
    side = max(edges, key=edges.get)
    return (side, edges[side]) if edges[side] >= threshold else (None, None)


def flat_profit(price: float | None, won: bool | None) -> float | None:
    """1-unit stake at American `price`: decimal - 1 on a win, -1 on a loss, 0 on a push (won None)."""
    d = american_to_decimal(price)
    if d is None:
        return None
    if won is None:
        return 0.0
    return d - 1 if won else -1.0


def score_team(log: dict, home_score: int, away_score: int, close: dict | None) -> dict:
    """Score dict for one logged team prediction (log: prediction_log fields; close: closing snapshot fields)."""
    y = int(home_score > away_score)
    p = log["home_win_prob"]
    logged_p = log.get("market_home_prob_novig")
    close_p = close.get("home_prob_novig") if close else None
    side, edge = pick_side(p, logged_p, ("home", "away"))
    out = {"stat": "home_win", "status": "scored", "actual": float(y), "model_prob": p, "outcome": y,
           "log_loss": log_loss(p, y), "market_prob_logged": logged_p, "market_prob_close": close_p,
           "market_log_loss_logged": log_loss(logged_p, y), "market_log_loss_close": log_loss(close_p, y),
           "clv_prob": clv_prob(p, logged_p, close_p), "bet_side": side, "bet_edge": edge}
    if side:
        logged_price = log.get(f"market_{side}_moneyline")
        close_price = close.get(f"{side}_moneyline") if close else None
        out.update(bet_price_logged=logged_price, bet_price_close=close_price,
                   clv_price=price_clv(logged_price, close_price),
                   bet_profit=flat_profit(logged_price, y == (side == "home")))
    return out


def score_player(log: dict, actual: float | None, close_rows: list | None) -> dict:
    """Score dict for one logged player stat (log: player_prediction_log fields; actual None = no result)."""
    from .predict import prop_probability
    out = {"stat": log["stat"], "expected": log["expected"], "actual": actual, "line": log.get("market_line")}
    if actual is None:
        return {**out, "status": "no_result"}
    out["poisson_deviance"] = poisson_deviance(actual, log["expected"])
    line, key = log.get("market_line"), PROP_KEYS.get(log["stat"])
    if line is None or key is None:
        return {**out, "status": "no_line"}
    expected = {log["stat"]: log["expected"]}
    p_over = prop_probability(expected, key, line, "over")
    p_under = prop_probability(expected, key, line, "under")
    logged_p = log.get("market_over_prob_novig")
    close = prop_consensus([r for r in close_rows or [] if _get(r, "prop_type") == log["stat"]], line) if close_rows else None
    close_p = close["p_over"] if close else None
    side, edge = pick_side(p_over, logged_p, ("over", "under"), p_second=p_under)
    push = actual == line
    y = None if push else int(actual > line)
    out.update(status="push" if push else "scored", model_prob=p_over, outcome=y, log_loss=log_loss(p_over, y),
               market_prob_logged=logged_p, market_prob_close=close_p,
               market_log_loss_logged=log_loss(logged_p, y), market_log_loss_close=log_loss(close_p, y),
               clv_prob=clv_prob(p_over, logged_p, close_p), bet_side=side, bet_edge=edge)
    if side:
        logged_price = log.get(f"market_{side}_price")
        close_price = close.get(f"{side}_price") if close else None
        out.update(bet_price_logged=logged_price, bet_price_close=close_price,
                   clv_price=price_clv(logged_price, close_price),
                   bet_profit=flat_profit(logged_price, None if push else (y == 1) == (side == "over")))
    return out


# ---------- logging ----------

def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def nhl_today(now: datetime.datetime) -> int:
    """North American game day (UTC shifted back 12 hours, as predictions.predict._today)."""
    return int((now - datetime.timedelta(hours=12)).strftime("%Y%m%d"))


async def _already_logged(db: AsyncSession, game_id: int, version: str, run_id: str) -> bool:
    """One frozen log per game per model version: a retry or a later run of the same model skips games already
    logged, whatever hour they were logged in (run_id is kept for the record)."""
    for model in (PredictionLog, PlayerPredictionLog):
        hit = await db.execute(select(model.id).where(model.game_id == game_id, model.model_version == version).limit(1))
        if hit.first():
            return True
    return False


async def unlogged_game_ids(db: AsyncSession, game_ids: list[int]) -> list[int]:
    """The games in `game_ids` the current model version hasn't logged yet (as _already_logged)."""
    version = model_version()
    logged = set()
    for model in (PredictionLog, PlayerPredictionLog):
        result = await db.execute(select(model.game_id).where(model.game_id.in_(game_ids), model.model_version == version))
        logged.update(result.scalars())
    return [g for g in game_ids if g not in logged]


async def _roster(db: AsyncSession, teams: list[str]) -> list[tuple[int, str, str]]:
    result = await db.execute(select(Player.id, Player.current_team_tri_code, Player.position)
                              .where(Player.current_team_tri_code.in_(teams)))
    return [(pid, team, pos) for pid, team, pos in result.all()]


async def log_predictions(db: AsyncSession, game_date: int | None = None, now: datetime.datetime | None = None,
                          run_id: str | None = None, include_started: bool = False, players: bool = True,
                          game_ids: list[int] | None = None) -> dict:
    """Logs predictions for `game_date`'s games (default: today's NHL date) that haven't started yet, or only
    `game_ids` among them (the pre-game log of the games about to start).
    run_id defaults to the UTC hour, so a retried run in the same hour fills in only the games it missed."""
    from . import predict as P
    now = as_utc(now) or _now()
    game_date = game_date or nhl_today(now)
    run_id = run_id or now.strftime("%Y%m%dT%H")
    version = model_version()
    games = (await db.execute(select(Games).where(Games.date == game_date).order_by(Games.start_time))).scalars().all()
    games = [g for g in games if include_started or (g.game_state not in FINISHED_GAME_STATES and as_utc(g.start_time) > now)]
    if game_ids is not None:
        wanted = set(game_ids)
        games = [g for g in games if g.id in wanted]
    summary = {"run_id": run_id, "model_version": version, "game_date": game_date, "games": len(games),
               "team_rows": 0, "player_rows": 0, "skipped_logged": 0, "no_team_prediction": 0, "player_failures": 0,
               "goalies_not_starting": 0}
    if not games:
        return summary
    game_snaps = await latest_game_snapshots(db, [g.id for g in games], now)
    prop_snaps = await latest_prop_snapshots(db, [g.id for g in games], now)
    # fallback market where ESPN has no line: PropLine's quotes (fetched by the odds pipelines) as they stood now
    api_rows = quote_book_rows(await get_quotes_for_games(db, [g.id for g in games]), now)
    # rebuild the cached prediction context so just-fetched starters and odds are used
    P.invalidate_team_context()
    try:
        await P.refresh_team_context(db)
    except Exception as e:
        print(f"prediction log: team context rebuild failed ({e!r}); each game reports its own failure")
    # plain copies: a rollback after one game's failure expires ORM objects, and reloading them here would fail
    games = [SimpleNamespace(id=g.id, date=g.date, season=g.season, start_time=g.start_time,
                             home_team_tri_code=g.home_team_tri_code, away_team_tri_code=g.away_team_tri_code)
             for g in games]
    for game in games:
        if await _already_logged(db, game.id, version, run_id):
            summary["skipped_logged"] += 1
            continue
        try:
            await _log_game(db, game, base_row(run_id, version, now, game), game_snaps, prop_snaps, api_rows,
                            players, summary)
            await db.commit()  # per game, so a crash keeps the games already logged
        except Exception as e:   # one game's failure must not lose the rest of the day
            await db.rollback()
            summary["game_failures"] = summary.get("game_failures", 0) + 1
            print(f"prediction log: game {game.id} failed: {e!r}")
    # which injury report the lineups used (None: no report in the last 36 hours, previous-game lineups)
    report_at = P._context.get("injury_report_at")
    summary["injury_report_at"] = report_at.isoformat() if report_at is not None else None
    return summary


def base_row(run_id, version, now, game) -> dict:
    return {"run_id": run_id, "model_version": version, "logged_at": now, "game_id": game.id, "game_date": game.date}


async def _expected_skaters(db: AsyncSession, game) -> tuple[set | None, set]:
    """(skaters expected to dress, players the injury report keeps out). The expected skaters are the live lineups
    behind the roster rating (previous game's, minus players listed out plus their replacements), so scratches and
    injured players aren't logged."""
    from . import predict as P
    try:
        ctx = await P._team_context(db)
    except (LookupError, FileNotFoundError):
        return None, set()
    out = ctx.get("injured_out")
    # listed out for this game (a listing covers games up to the day before ESPN's estimated return)
    out = set(out.index[out >= game.date]) if out is not None else set()
    lineups = ctx.get("lineups")
    if lineups is None:
        return None, out
    return set(lineups.loc[lineups["game_id"] == game.id, "player_id"].astype(int)), out


async def _log_game(db: AsyncSession, game, base: dict, game_snaps, prop_snaps, api_rows, players: bool,
                    summary: dict) -> None:
    from . import predict as P
    probs = await P.get_upcoming_game_prediction(game, db)
    if probs is None:
        summary["no_team_prediction"] += 1
    else:
        snap = game_snaps.get(game.id)
        db.add(PredictionLog(**base, start_time=game.start_time, home_team_tri_code=game.home_team_tri_code,
                             away_team_tri_code=game.away_team_tri_code, home_win_prob=probs[0],
                             market_captured_at=snap.captured_at if snap else None,
                             market_home_prob_novig=snap.home_prob_novig if snap else None,
                             market_home_moneyline=snap.home_moneyline if snap else None,
                             market_away_moneyline=snap.away_moneyline if snap else None))
        summary["team_rows"] += 1
    if players:
        by_market = defaultdict(list)
        for r in prop_snaps.get(game.id, []):
            by_market[(r.player_id, r.prop_type)].append(r)
        dressing, listed_out = await _expected_skaters(db, game)
        for pid, team, pos in await _roster(db, [game.home_team_tri_code, game.away_team_tri_code]):
            role = "goalie" if pos == "G" else "skater"
            if role == "skater" and pid in listed_out:
                summary["skaters_listed_out"] = summary.get("skaters_listed_out", 0) + 1
                continue
            if role == "skater" and dressing and pid not in dressing:
                summary["skaters_not_expected"] = summary.get("skaters_not_expected", 0) + 1
                continue
            try:
                pred = await (P.predict_goalie if role == "goalie" else P.predict_skater)(db, pid, team, game)
            except Exception as e:  # one player's odd history must not stop the rest
                summary["player_failures"] += 1
                print(f"prediction log: {role} {pid} game {game.id} failed: {e!r}")
                continue
            if role == "goalie" and pred and pred.get("starting") is False:
                summary["goalies_not_starting"] += 1  # rates assume he starts; skip the expected backup
                continue
            for stat, expected in (pred or {}).items():
                # numeric model outputs only (not prob_* duplicates or starter metadata)
                if (stat.startswith("prob_") or isinstance(expected, bool) or not isinstance(expected, (int, float))
                        or not math.isfinite(expected)):
                    continue
                m, source, captured_at = pick_market(by_market.get((pid, stat)), api_rows.get((game.id, pid, stat)))
                db.add(PlayerPredictionLog(
                    **base, player_id=pid, team_tri_code=team, role=role, stat=stat, expected=float(expected),
                    market_captured_at=captured_at, market_source=source,
                    market_line=m["line"] if m else None, market_over_price=m["over_price"] if m else None,
                    market_under_price=m["under_price"] if m else None,
                    market_over_prob_novig=m["p_over"] if m else None, market_n_books=m["n_books"] if m else None))
                summary["player_rows"] += 1
                summary[f"player_lines_{source or 'none'}"] = summary.get(f"player_lines_{source or 'none'}", 0) + 1


# ---------- scoring ----------

def market_source(log) -> str | None:
    """Feed of a logged player line. Rows logged before market_source existed took their line from ESPN."""
    if log.market_line is None:
        return None
    return log.market_source or "espn"


# market_source values whose line came from prop_quotes (closing rows from quote_closing_rows)
QUOTE_SOURCES = ("propline", "odds_api")


async def quote_closing_rows(db: AsyncSession, starts: dict) -> dict[int, list[dict]]:
    """game_id -> two-sided multi-book quote rows as they stood at puck drop (the last fetch before the start)."""
    out: dict[int, list[dict]] = defaultdict(list)
    quotes = defaultdict(list)
    for q in await get_quotes_for_games(db, list(starts)):
        quotes[q.game_id].append(q)
    for gid, qs in quotes.items():
        if starts.get(gid) is None:
            continue
        for rows in quote_book_rows(qs, as_utc(starts[gid]) - datetime.timedelta(seconds=1)).values():
            out[gid].extend(rows)
    return dict(out)

def _columns(obj, names) -> dict:
    return {n: getattr(obj, n) for n in names}

_TEAM_LOG_FIELDS = ("home_win_prob", "market_home_prob_novig", "market_home_moneyline", "market_away_moneyline")
_PLAYER_LOG_FIELDS = ("stat", "expected", "market_line", "market_over_price", "market_under_price", "market_over_prob_novig")


def _days_since(game_date: int, now: datetime.datetime) -> int:
    return (now.date() - datetime.datetime.strptime(str(game_date), "%Y%m%d").date()).days


def skater_actuals(log: SkaterGameLog) -> dict:
    return {"goals": log.goals, "assists": log.primary_assists + log.secondary_assists, "points": log.points,
            "shots_on_goal": log.shots_on_goal, "hits": log.hits, "blocked_shots": log.blocked_shots,
            "pp_points": log.pp_points}


def goalie_actuals(log: GoalieGameLog) -> dict:
    return {"goals_against": log.goals_against, "sog": log.sog, "saves": log.sog - log.goals_against}


async def _unscored(db: AsyncSession, model, kind: str):
    scored = select(PredictionScore.log_id).where(PredictionScore.kind == kind)
    stmt = (select(model, Games).join(Games, Games.id == model.game_id)
            .where(model.id.not_in(scored), Games.game_state.in_(FINISHED_GAME_STATES)))
    return (await db.execute(stmt)).all()


async def score_predictions(db: AsyncSession, now: datetime.datetime | None = None) -> dict:
    """Scores every logged row whose game is final and not yet scored. Rows wait for a closing snapshot up to
    CLOSE_WAIT_DAYS and for player logs up to RESULT_WAIT_DAYS, so a late scrape still gets scored correctly."""
    now = as_utc(now) or _now()
    summary = defaultdict(int)
    team_rows = await _unscored(db, PredictionLog, "team")
    team_close = await closing_game_snapshots(db, list({log.game_id for log, _ in team_rows}))
    for log, game in team_rows:
        if game.home_score is None or game.away_score is None:
            continue
        close = team_close.get(log.game_id)
        if close is None and _days_since(game.date, now) < CLOSE_WAIT_DAYS:
            summary["team_waiting_close"] += 1
            continue
        s = score_team(_columns(log, _TEAM_LOG_FIELDS), game.home_score, game.away_score,
                       _columns(close, ("home_prob_novig", "home_moneyline", "away_moneyline")) if close else None)
        db.add(PredictionScore(kind="team", log_id=log.id, run_id=log.run_id, model_version=log.model_version,
                               game_id=log.game_id, game_date=log.game_date, scored_at=now, **s))
        summary["team_scored"] += 1

    player_rows = await _unscored(db, PlayerPredictionLog, "player")
    game_ids = list({log.game_id for log, _ in player_rows})
    prop_close = await closing_prop_snapshots(db, game_ids)
    api_close = await quote_closing_rows(db, {game.id: game.start_time for _, game in player_rows})
    actuals: dict[tuple, dict] = {}
    games_with_logs: set[tuple[int, str]] = set()
    if game_ids:
        for row in (await db.execute(select(SkaterGameLog).where(SkaterGameLog.game_id.in_(game_ids)))).scalars():
            actuals[(row.game_id, row.player_id, "skater")] = skater_actuals(row)
            games_with_logs.add((row.game_id, "skater"))
        for row in (await db.execute(select(GoalieGameLog).where(GoalieGameLog.game_id.in_(game_ids)))).scalars():
            actuals[(row.game_id, row.player_id, "goalie")] = goalie_actuals(row)
            games_with_logs.add((row.game_id, "goalie"))
    for log, game in player_rows:
        waited = _days_since(game.date, now)
        if (log.game_id, log.role) not in games_with_logs:
            if waited < RESULT_WAIT_DAYS:
                summary["player_waiting_logs"] += 1
                continue
            s = {"stat": log.stat, "expected": log.expected, "line": log.market_line, "status": "no_result"}
        elif (market_source(log) == "espn" and log.game_id not in prop_close and waited < CLOSE_WAIT_DAYS):
            # PropLine / Odds API quotes are only fetched before puck drop, so their close is already final; ESPN's frozen
            # close arrives with the nightly fetch after the game
            summary["player_waiting_close"] += 1
            continue
        else:
            stats = actuals.get((log.game_id, log.player_id, log.role))
            if stats is None:
                s = {"stat": log.stat, "expected": log.expected, "line": log.market_line, "status": "dnp"}
            else:
                value = stats.get(log.stat)
                # the close from the feed the logged line came from, this player's quotes only (the game's
                # snapshots hold every player's props)
                close_rows = api_close if market_source(log) in QUOTE_SOURCES else prop_close
                mine = [r for r in close_rows.get(log.game_id, []) if _get(r, "player_id") == log.player_id]
                s = score_player(_columns(log, _PLAYER_LOG_FIELDS), None if value is None else float(value), mine or None)
        db.add(PredictionScore(kind="player", log_id=log.id, run_id=log.run_id, model_version=log.model_version,
                               game_id=log.game_id, game_date=log.game_date, player_id=log.player_id,
                               scored_at=now, **s))
        summary[f"player_{s['status']}"] += 1
    await db.commit()
    return dict(summary)


# ---------- report ----------

def _mean(values) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 5) if vals else None


def calibration(rows: list[dict], buckets: int = 10) -> list[dict]:
    out = []
    for b in range(buckets):
        lo, hi = b / buckets, (b + 1) / buckets
        sel = [r for r in rows if r["model_prob"] is not None and r["outcome"] is not None
               and (lo <= r["model_prob"] < hi or (b == buckets - 1 and r["model_prob"] == 1))]
        if sel:
            out.append({"bucket": f"{lo:.1f}-{hi:.1f}", "n": len(sel), "mean_pred": _mean(r["model_prob"] for r in sel),
                        "observed": _mean(r["outcome"] for r in sel)})
    return out


def summarize(rows: list[dict]) -> dict:
    """Aggregate score rows of one group (team, or one player stat)."""
    priced = [r for r in rows if r["outcome"] is not None and r["market_prob_logged"] is not None]
    closed = [r for r in priced if r["market_prob_close"] is not None]
    bets = [r for r in rows if r["bet_side"] and r["bet_profit"] is not None]
    return {
        "n": len(rows),
        "status": dict(sorted(Counter(r["status"] for r in rows).items())),
        "poisson_deviance": _mean(r["poisson_deviance"] for r in rows),
        "n_outcomes": sum(1 for r in rows if r["outcome"] is not None),
        "log_loss": _mean(r["log_loss"] for r in rows if r["outcome"] is not None),
        # head to head on rows that have the market price too
        "vs_market_logged": {"n": len(priced), "model": _mean(r["log_loss"] for r in priced),
                             "market": _mean(r["market_log_loss_logged"] for r in priced)},
        "vs_market_close": {"n": len(closed), "model": _mean(r["log_loss"] for r in closed),
                            "market": _mean(r["market_log_loss_close"] for r in closed)},
        "clv_prob_mean": _mean(r["clv_prob"] for r in rows),
        "calibration": calibration(rows),
        "bets": {"threshold": EDGE_THRESHOLD, "n": len(bets),
                 "clv_price_mean": _mean(r["clv_price"] for r in bets),
                 "beat_close_rate": _mean(float(r["clv_price"] > 0) for r in bets if r["clv_price"] is not None),
                 "roi": _mean(r["bet_profit"] for r in bets)},
    }


async def model_report(db: AsyncSession, model_version_filter: str | None = None, start: int | None = None,
                       end: int | None = None) -> dict:
    """Forward-test summary from prediction_scores. Only each prediction's last pre-game run counts. Player stats
    are also split by the feed their logged line came from (`player_by_source`), and `coverage` counts every logged
    player row, scored or not, with and without a line per feed."""
    stmt = select(PredictionScore, PlayerPredictionLog.market_source).outerjoin(
        PlayerPredictionLog, and_(PredictionScore.kind == "player", PredictionScore.log_id == PlayerPredictionLog.id))
    if model_version_filter:
        stmt = stmt.where(PredictionScore.model_version == model_version_filter)
    if start:
        stmt = stmt.where(PredictionScore.game_date >= start)
    if end:
        stmt = stmt.where(PredictionScore.game_date <= end)
    latest: dict[tuple, dict] = {}
    for s, source in (await db.execute(stmt)).all():
        row = {c.name: getattr(s, c.name) for c in PredictionScore.__table__.columns}
        row["market_source"] = source or ("espn" if s.kind == "player" and s.line is not None else None)
        key = (s.kind, s.model_version, s.game_id, s.player_id, s.stat)
        if key not in latest or row["run_id"] > latest[key]["run_id"]:
            latest[key] = row
    rows = list(latest.values())
    groups: dict[str, list] = defaultdict(list)
    by_source: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        groups["team" if r["kind"] == "team" else f"player:{r['stat']}"].append(r)
        if r["kind"] == "player" and r["market_source"]:
            by_source[r["stat"]][r["market_source"]].append(r)
    dates = [r["game_date"] for r in rows]
    return {"model_versions": sorted({r["model_version"] for r in rows}), "edge_threshold": EDGE_THRESHOLD,
            "game_dates": [min(dates), max(dates)] if dates else None,
            "groups": {name: summarize(g) for name, g in sorted(groups.items())},
            # head to head per feed, without the calibration table (it's in `groups`)
            "player_by_source": {stat: {src: {k: v for k, v in summarize(g).items() if k != "calibration"}
                                        for src, g in sorted(srcs.items())}
                                 for stat, srcs in sorted(by_source.items())},
            "coverage": await log_coverage(db, model_version_filter, start, end),
            "unlogged_games": await unlogged_games(db, start, end)}


async def unlogged_games(db: AsyncSession, start: int | None = None, end: int | None = None) -> dict:
    """Finished regular-season/playoff games with no prediction_log row, per game date, from the first logged date
    (or `start`) on: days the afternoon run never happened (machine asleep, container down). They can't be logged
    after the fact, so they're gaps in the forward test, not pending work."""
    first = start or (await db.execute(select(func.min(PredictionLog.game_date)))).scalar()
    if first is None:
        return {"since": None, "games": 0, "by_date": {}}
    logged = select(PredictionLog.game_id)
    stmt = select(Games.id, Games.date).where(Games.date >= first, Games.game_state.in_(FINISHED_GAME_STATES),
                                              Games.id.not_in(logged))
    if end:
        stmt = stmt.where(Games.date <= end)
    by_date: Counter = Counter()
    for game_id, date in (await db.execute(stmt)).all():
        if game_id // 10_000 % 100 in (2, 3):
            by_date[date] += 1
    return {"since": first, "games": sum(by_date.values()), "by_date": dict(sorted(by_date.items()))}


async def log_coverage(db: AsyncSession, model_version_filter: str | None = None, start: int | None = None,
                       end: int | None = None) -> dict:
    """How many logged player rows had a market line, per priced stat and per feed (espn / propline / odds_api /
    none), and how
    many logged games had any line from each feed. Counts every logged row (scored or not), so it can be checked
    the morning after the first runs. Each (game, player, stat) counts once: its last run of the latest version."""
    stmt = select(PlayerPredictionLog.game_id, PlayerPredictionLog.game_date, PlayerPredictionLog.player_id,
                  PlayerPredictionLog.stat, PlayerPredictionLog.model_version, PlayerPredictionLog.run_id,
                  PlayerPredictionLog.market_line, PlayerPredictionLog.market_source).where(
        PlayerPredictionLog.stat.in_(list(PROP_KEYS)))
    if model_version_filter:
        stmt = stmt.where(PlayerPredictionLog.model_version == model_version_filter)
    if start:
        stmt = stmt.where(PlayerPredictionLog.game_date >= start)
    if end:
        stmt = stmt.where(PlayerPredictionLog.game_date <= end)
    latest: dict[tuple, tuple] = {}
    for r in (await db.execute(stmt)).all():
        key = (r.game_id, r.player_id, r.stat)
        if key not in latest or (r.model_version, r.run_id) > (latest[key].model_version, latest[key].run_id):
            latest[key] = r
    stats: dict[str, Counter] = defaultdict(Counter)
    games: dict[int, set] = defaultdict(set)
    for r in latest.values():
        source = market_source(r) or "none"
        stats[r.stat][source] += 1
        games[r.game_id].add(source)
    def share(counter: Counter, n: int) -> dict:
        return {src: {"n": counter[src], "share": round(counter[src] / n, 4) if n else None}
                for src in ("espn", "propline", "odds_api", "none")}
    out_stats = {}
    for stat, counter in sorted(stats.items()):
        n = sum(counter.values())
        out_stats[stat] = {"rows": n, **share(counter, n)}
    game_counter = Counter(src for sources in games.values() for src in sources if src != "none")
    return {"rows": len(latest), "games": len(games),
            "games_with_line": {src: game_counter[src] for src in ("espn", "propline", "odds_api")},
            "games_without_any_line": sum(1 for sources in games.values() if sources == {"none"}),
            "stats": out_stats}


# ---------- CLI ----------

async def _cli(args) -> None:
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        if args.cmd == "log":
            out = await log_predictions(db, game_date=args.date, run_id=args.run_id, players=not args.no_players)
        elif args.cmd == "score":
            out = await score_predictions(db)
        else:
            out = await model_report(db, args.model_version, args.start, args.end)
    print(json.dumps(out, indent=1, default=str))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Forward-test prediction log")
    sub = parser.add_subparsers(dest="cmd", required=True)
    log = sub.add_parser("log")
    log.add_argument("--date", type=int)
    log.add_argument("--run-id")
    log.add_argument("--no-players", action="store_true")
    sub.add_parser("score")
    rep = sub.add_parser("report")
    rep.add_argument("--model-version")
    rep.add_argument("--start", type=int)
    rep.add_argument("--end", type=int)
    asyncio.run(_cli(parser.parse_args(argv)))


if __name__ == "__main__":
    main()
