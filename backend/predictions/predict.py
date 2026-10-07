import asyncio
import datetime
import time
import joblib
import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from . import features as F
from .config import PROP_DISPERSION, SKATER_BUNDLE, GOALIE_BUNDLE, TEAM_BUNDLE, SKATER_TARGETS, GOALIE_TARGETS, GOALIE_TREND_TARGETS
from .data import (load_skater_logs, load_goalie_logs, load_team_stats, load_games, load_current_rosters, load_game_odds,
                   load_game_mates)

_bundles: dict = {}

def load_bundle(path) -> dict:
    """Loads a saved model bundle, reloading it when nightly training rewrites the file."""
    if not path.exists():
        raise FileNotFoundError(f"No saved models at {path}. Train the models first.")
    mtime = path.stat().st_mtime
    cached = _bundles.get(path)
    if cached is None or cached[0] != mtime:
        cached = (mtime, joblib.load(path))
        _bundles[path] = cached
    return cached[1]

# ---------- league-wide team context (shared by every prediction) ----------

CONTEXT_TTL_SECONDS = 600
_context: dict = {"built_at": 0.0}
_context_lock = asyncio.Lock()

def _today() -> int:
    """The current NHL game day. Game dates are North American, so UTC shifted back 12 hours keeps tonight's
    games "today" until noon UTC instead of dropping them at midnight UTC (the container's clock)."""
    now = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=12)
    return int(now.strftime("%Y%m%d"))

def _placeholder_games(games: pd.DataFrame, played_ids: set) -> pd.DataFrame:
    """Games without game logs that still belong in team history: upcoming games (to compute their pre-game
    features) and games already finished but not scraped yet (so rest days and back-to-backs stay right).
    Past games that never finished (postponed, stale state) are left out."""
    missing = games[~games["id"].isin(played_ids)]
    return missing[missing["home_score"].notna() | (missing["date"] >= _today())]

def _placeholder_team_rows(games: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for g in games.itertuples():
        for team, opponent, is_home in ((g.home_team_tri_code, g.away_team_tri_code, 1.0),
                                        (g.away_team_tri_code, g.home_team_tri_code, 0.0)):
            rows.append({"game_id": g.id, "team": team, "opponent": opponent, "season": g.season,
                         "game_date": g.date, "is_home": is_home})
    return pd.DataFrame(rows)

def _live_lineups(team_games: pd.DataFrame, skaters: pd.DataFrame, rosters: pd.DataFrame, ratings: pd.DataFrame,
                  out: pd.Series | None = None, upcoming=()) -> pd.DataFrame:
    """Expected lineups for every team-game: the previous game's lineup this season, or the current roster
    for a team that hasn't played yet this season. In `upcoming` games, players the injury report lists out (`out`)
    are replaced by the team's best healthy extra skater on the current roster (features.drop_listed_out)."""
    out = out if out is not None else pd.Series(dtype="int64")
    lineups = F.expected_lineups(skaters, team_games)
    missing = team_games[~team_games.set_index(["game_id", "team"]).index.isin(lineups.set_index(["game_id", "team"]).index)]
    lineups = pd.concat([lineups, F.roster_lineups(rosters, missing, ratings)], ignore_index=True)
    if out.empty:
        return lineups
    logged = skaters.drop_duplicates("player_id", keep="last") if "position" in skaters else pd.DataFrame(columns=["player_id", "position"])
    positions = pd.concat([logged.set_index("player_id")["position"], rosters.set_index("player_id")["position"]])
    positions = positions[~positions.index.duplicated(keep="last")]   # current roster position wins
    candidates = rosters.merge(ratings[["player_id", "exp_toi"]], on="player_id", how="left")
    return F.drop_listed_out(lineups, out, positions, candidates, game_ids=set(upcoming))

def _injured_out(injuries: pd.DataFrame | None, skaters: pd.DataFrame, goalies: pd.DataFrame) -> pd.Series:
    """Players the latest injury report keeps out (player_id -> last game day covered, features.listed_out), minus
    those seen playing since their entry was updated."""
    if injuries is None or injuries.empty:
        return pd.Series(dtype="int64")
    played = [df[["player_id", "game_date"]] for df in (skaters, goalies) if not df.empty]
    last_played = pd.concat(played).groupby("player_id")["game_date"].max() if played else None
    return F.listed_out(injuries, _today(), last_played)

def _build_context(team_stats: pd.DataFrame, games: pd.DataFrame, goalies: pd.DataFrame, skaters: pd.DataFrame,
                   rosters: pd.DataFrame, odds: pd.DataFrame, team_mtime, known_starters: pd.DataFrame | None = None,
                   injuries: pd.DataFrame | None = None) -> dict:
    placeholders = _placeholder_games(games, set(team_stats["game_id"]))
    team_games = F.build_team_games(pd.concat([team_stats, _placeholder_team_rows(placeholders)], ignore_index=True))
    team_feats = F.team_history_features(team_games)
    # the injury report (player_injuries) applies to games not played yet; without one, lineups are as before
    upcoming = set(placeholders.loc[placeholders["home_score"].isna() & (placeholders["date"] >= _today()), "id"])
    season = int(games["season"].max())
    out = _injured_out(injuries, skaters, goalies[goalies["season"] == season] if not goalies.empty else goalies)
    # starters: confirmed/probable (game_starters table) for upcoming games, else the projection; actual starters
    # for played games, as in training. A projected starter listed out gives way to the team's healthy goalie.
    picks = F.starter_picks(team_games, goalies, known_starters, prefer_actual=True) if not goalies.empty else None
    if picks is not None and not out.empty:
        recent = goalies[goalies["season"] >= season - 1]
        picks = F.replace_out_starters(picks, out, team_games, recent, rosters, upcoming)
    starters = F.starter_features(team_games, goalies, picks=picks) if picks is not None else None
    win_probs: dict[int, float] = {}
    model_goals = None
    lineups = None
    # latest skater ratings are saved with both the team and skater models, so teammate quality works with either
    ratings = None
    for path in (TEAM_BUNDLE, SKATER_BUNDLE):
        if path.exists() and "skater_ratings" in load_bundle(path):
            ratings = load_bundle(path)["skater_ratings"]
            break
    live = None
    if ratings is not None:
        current = team_games[team_games["season"] == team_games["season"].max()]
        live = _live_lineups(current, skaters, rosters, ratings, out, upcoming)
        # the same lineups, per skater, for each player's teammate quality
        lineups = F.rated_lineups(live, ratings)
    if team_mtime is not None and live is not None:
        bundle = load_bundle(TEAM_BUNDLE)
        side_feats = [starters] if starters is not None else []
        side_feats.append(F.roster_ratings(live, ratings))
        frame = F.build_team_model_frame(games, team_feats, side_feats)
        frame = frame[frame["home_score"].isna() & (frame["date"] >= _today()) & frame["home_games_season"].notna()]
        if not frame.empty:
            p = bundle["model"].predict_proba(frame[bundle["features"]])[:, 1]
            win_probs = dict(zip(frame["game_id"].astype(int), p.astype(float)))
            if "goals" in bundle:
                model_goals = F.model_team_goals(frame, bundle["goals"])
    # player models also see the market's implied goals (stored nightly, incl. today's pre-game prices); games
    # without odds get the team goals model's expected goals instead
    player_ctx = F.add_player_context(team_feats, F.implied_team_goals(games, odds), starters, fallback=model_goals)
    if picks is not None:
        picks = picks[picks["game_id"].isin(placeholders["id"])].set_index(["game_id", "team"])
    return {"team_feats": player_ctx, "win_probs": win_probs, "placeholders": placeholders, "lineups": lineups,
            "starter_picks": picks, "injured_out": out,
            "injury_report_at": injuries["fetched_at"].max() if injuries is not None and not injuries.empty else None}

async def _load_known_starters(db: AsyncSession) -> pd.DataFrame | None:
    """Confirmed / probable starters from game_starters (None if the table is missing or unreadable)."""
    from app.crud.game_starters import load_game_starters
    try:
        return await load_game_starters(db)
    except Exception as e:
        await db.rollback()
        print(f"Could not load game_starters, using projected starters: {e!r}")
        return None

async def _load_injuries(db: AsyncSession) -> pd.DataFrame | None:
    """The latest injury report fetched in the last 36 hours (None if there is none, or the table is unreadable)."""
    from app.crud.player_injuries import load_injury_report
    try:
        return await load_injury_report(db)
    except Exception as e:
        await db.rollback()
        print(f"Could not load player_injuries, using previous-game lineups: {e!r}")
        return None

async def _team_context(db: AsyncSession) -> dict:
    """Pre-game team features and win probabilities for every scheduled game, rebuilt at most every 10 minutes."""
    async with _context_lock:   # concurrent cache misses wait for one rebuild instead of each doing it
        team_mtime = TEAM_BUNDLE.stat().st_mtime if TEAM_BUNDLE.exists() else None
        if time.monotonic() - _context["built_at"] < CONTEXT_TTL_SECONDS and _context.get("team_mtime") == team_mtime:
            return _context
        team_stats = await load_team_stats(db)
        games = await load_games(db)
        if team_stats.empty or games.empty:
            raise LookupError("No team stats or games in the DB to predict from")
        goalies = await load_goalie_logs(db)
        # lineups only need this season's games; player ratings come from the saved team model
        skaters = await load_skater_logs(db, seasons=[int(games["season"].max())])
        rosters = await load_current_rosters(db)
        odds = await load_game_odds(db)
        # the Elo loop, starter guesses and groupbys take a moment, so keep them off the event loop
        known_starters = await _load_known_starters(db)
        injuries = await _load_injuries(db)
        built = await asyncio.to_thread(_build_context, team_stats, games, goalies, skaters, rosters, odds, team_mtime,
                                        known_starters=known_starters, injuries=injuries)
        _context.update(built, built_at=time.monotonic(), team_mtime=team_mtime)
        return _context

def _upcoming_player_rows(logs: pd.DataFrame, game, team: str, placeholders: pd.DataFrame) -> pd.DataFrame:
    """The target game plus any of the team's finished-but-unscraped games since the player's last log,
    so rest days match what training saw. Stats are unknown, so they only shape the schedule features."""
    last_logged = logs["game_date"].max()
    on_team = (placeholders["home_team_tri_code"] == team) | (placeholders["away_team_tri_code"] == team)
    between = placeholders[on_team & placeholders["home_score"].notna()
                           & (placeholders["date"] > last_logged) & (placeholders["date"] < game.date)]
    targets = [(g.id, g.season, g.date, g.home_team_tri_code, g.away_team_tri_code) for g in between.itertuples()]
    targets.append((game.id, game.season // 10000, game.date, game.home_team_tri_code, game.away_team_tri_code))
    rows = []
    for game_id, season, date, home, away in targets:
        is_home = home == team
        row = {"game_id": game_id, "player_id": logs["player_id"].iloc[0], "season": season, "game_date": date,
               "team": team, "is_home": float(is_home), "opponent": away if is_home else home}
        if "position" in logs:
            row["position"] = logs["position"].iloc[0]
        rows.append(row)
    return pd.DataFrame(rows)

# ---------- public API ----------

async def get_upcoming_game_prediction(game, db: AsyncSession) -> list[float] | None:
    """[P(home win), P(away win)] for a scheduled game, or None if either team lacks history."""
    if not TEAM_BUNDLE.exists():
        return None
    try:
        p_home = (await _team_context(db))["win_probs"].get(game.id)
    except LookupError:
        return None
    if p_home is None:
        return None
    return [float(p_home), 1.0 - float(p_home)]

_shares_warned: list = []

async def _load_shares(db: AsyncSession, player_id: int, game_ids: list[int]) -> pd.DataFrame | None:
    """The player's stored shares (skater_game_shares) in `game_ids`; None if the table can't be read (not migrated)."""
    from sqlalchemy import select
    from app.models import SkaterGameShare as T
    cols = ["game_id", "player_id"] + F.SKATER_SHARE_STATS
    stmt = select(*(getattr(T, c) for c in cols)).where(T.player_id == player_id, T.game_id.in_(game_ids))
    try:
        # a savepoint, so a failed read doesn't roll back the caller's pending writes (the prediction log's rows)
        async with db.begin_nested():
            rows = (await db.execute(stmt)).all()
    except Exception as e:
        if not _shares_warned:   # once per process: the afternoon log would print it for every skater
            print(f"Could not read skater_game_shares, computing shares from game logs: {e!r}")
            _shares_warned.append(True)
        return None
    df = pd.DataFrame(rows, columns=cols)
    df[F.SKATER_SHARE_STATS] = df[F.SKATER_SHARE_STATS].astype(float)
    return df

async def _skater_shares(db: AsyncSession, player_id: int, game_ids: list[int]) -> pd.DataFrame:
    """`features.skater_shares` rows for the player's past games: the stored rows (refreshed nightly), plus any game
    not stored yet (scraped since the refresh, or no table) computed from every skater's log of that game."""
    stored = await _load_shares(db, player_id, game_ids)
    missing = game_ids if stored is None else sorted(set(game_ids) - set(stored["game_id"]))
    if not missing:
        return stored
    computed = F.skater_shares(await load_game_mates(db, missing))
    return computed if stored is None or stored.empty else pd.concat([stored, computed], ignore_index=True)

async def predict_skater(db: AsyncSession, player_id: int, team: str, game) -> dict | None:
    """Expected goals/assists/points in `game` and the chance of at least one of each. None without history."""
    bundle = load_bundle(SKATER_BUNDLE)
    logs = await load_skater_logs(db, [player_id])
    if logs.empty:
        return None
    ctx = await _team_context(db)
    upcoming = _upcoming_player_rows(logs, game, team, ctx["placeholders"])
    # deployment shares need every skater of the player's past games, so they come precomputed per game
    uses_shares = any(c in bundle["features"] for c in F.SKATER_SHARE_COLUMNS)
    shares = await _skater_shares(db, int(player_id), logs["game_id"].unique().tolist()) if uses_shares else None
    rows = pd.concat([logs, upcoming], ignore_index=True)
    # teammate quality is computed per team-game, so only the player's games of the season's lineups matter
    lineups = ctx.get("lineups")
    if lineups is not None:
        lineups = lineups[lineups["game_id"].isin(rows["game_id"])]
    df, _ = F.skater_features(rows, ctx["team_feats"], league_rates=bundle["league_rates"],
                              extra_stats=bundle.get("extra_stats", ()), shares=shares, lineups=lineups)
    X = df.loc[df["game_id"] == game.id, bundle["features"]].tail(1).astype(np.float32)
    trends = bundle.get("trends", {})
    expected = {t: float(m.predict(X, base_margin=np.log([trends[t]]) if t in trends else None)[0])
                for t, m in bundle["models"].items()}
    return {**expected, **{f"prob_{t}": float(1.0 - np.exp(-mu)) for t, mu in expected.items()}}

async def predict_goalie(db: AsyncSession, player_id: int, team: str, game) -> dict | None:
    """Expected goals against and shots on goal against if the goalie starts `game`. None without history."""
    bundle = load_bundle(GOALIE_BUNDLE)
    logs = await load_goalie_logs(db, [player_id])
    if logs.empty:
        return None
    ctx = await _team_context(db)
    upcoming = _upcoming_player_rows(logs, game, team, ctx["placeholders"])
    df = F.goalie_features(pd.concat([logs, upcoming], ignore_index=True), ctx["team_feats"])
    X = df.loc[df["game_id"] == game.id, bundle["features"]].tail(1).astype(np.float32)
    out = {}
    for t in bundle["models"]:
        margin = np.log([bundle["trends"][t]]) if t in bundle["trends"] else None
        out[t] = float(bundle["models"][t].predict(X, base_margin=margin)[0])
    return {**out, **goalie_start_info(ctx.get("starter_picks"), game.id, team, player_id)}

def goalie_start_info(picks: pd.DataFrame | None, game_id: int, team: str, player_id: int) -> dict:
    """Whether the goalie is his team's expected starter for the game (`starting`) and how sure that is
    (`starter_status`: confirmed / probable / projected; None when unknown). The rates above assume he starts."""
    try:
        pick = picks.loc[(game_id, team)] if picks is not None else None
    except KeyError:
        pick = None
    if pick is None or pd.isna(pick["player_id"]):
        return {"starting": None, "starter_status": None}
    return {"starting": int(pick["player_id"]) == int(player_id), "starter_status": str(pick["status"])}

# Odds API prop markets -> the model stat that settles them
PROP_STATS = {"player_goals": "goals", "player_assists": "assists", "player_points": "points",
              "player_shots_on_goal": "shots_on_goal", "player_total_saves": "saves",
              "player_blocked_shots": "blocked_shots", "player_hits": "hits", "player_goal_scorer_anytime": "goals"}
# player_power_play_points isn't priced: the model's pp_points counts 5-on-4 time only, while books settle on every
# power-play strength (5-on-3, 4-on-3, ...), so it would show false under edges

def prop_dispersion() -> dict:
    """Negative-binomial alpha per stat for prop pricing, as fitted on each bundle's validation split at training
    time (0 = Poisson). Config's PROP_DISPERSION fills in for bundles trained before alphas were saved, or missing."""
    alphas = dict(PROP_DISPERSION)
    for path in (SKATER_BUNDLE, GOALIE_BUNDLE):
        if path.exists():
            fitted = load_bundle(path).get("dispersion")
            if fitted is not None:
                alphas.update(fitted)
    return alphas

def prop_probability(expected: dict, prop_type: str, line: float, side: str, alphas: dict | None = None) -> float | None:
    """Chance the over/under (or yes) side of a prop wins under the model's rate for that stat. Counts are Poisson,
    except stats whose fitted dispersion (`alphas`, default `prop_dispersion()`) is positive, which use a negative
    binomial with variance mu(1 + alpha mu). Half-point lines can't push; a whole-number line's push counts as
    not winning."""
    from scipy.stats import poisson, nbinom
    stat = PROP_STATS.get(prop_type)
    if stat is None or stat not in expected:
        return None
    lam, alpha = expected[stat], (prop_dispersion() if alphas is None else alphas).get(stat, 0.0)
    if alpha > 0:
        n = 1 / alpha
        cdf = lambda k: nbinom.cdf(k, n, n / (n + lam))
    else:
        cdf = lambda k: poisson.cdf(k, lam)
    if side.lower() in ("over", "yes"):
        return float(1 - cdf(np.floor(line)))
    return float(cdf(np.ceil(line) - 1))
