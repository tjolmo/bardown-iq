import asyncio
import datetime
import time
import joblib
import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from . import features as F
from .config import PROP_DISPERSION, SKATER_BUNDLE, GOALIE_BUNDLE, TEAM_BUNDLE, SKATER_TARGETS, GOALIE_TARGETS, GOALIE_TREND_TARGETS
from .data import load_skater_logs, load_goalie_logs, load_team_stats, load_games, load_current_rosters, load_game_odds

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

def _live_lineups(team_games: pd.DataFrame, skaters: pd.DataFrame, rosters: pd.DataFrame, ratings: pd.DataFrame) -> pd.DataFrame:
    """Expected lineups for every team-game: the previous game's lineup this season, or the current roster
    for a team that hasn't played yet this season."""
    lineups = F.expected_lineups(skaters, team_games)
    missing = team_games[~team_games.set_index(["game_id", "team"]).index.isin(lineups.set_index(["game_id", "team"]).index)]
    return pd.concat([lineups, F.roster_lineups(rosters, missing, ratings)], ignore_index=True)

def _build_context(team_stats: pd.DataFrame, games: pd.DataFrame, goalies: pd.DataFrame, skaters: pd.DataFrame,
                   rosters: pd.DataFrame, odds: pd.DataFrame, team_mtime) -> dict:
    placeholders = _placeholder_games(games, set(team_stats["game_id"]))
    team_games = F.build_team_games(pd.concat([team_stats, _placeholder_team_rows(placeholders)], ignore_index=True))
    team_feats = F.team_history_features(team_games)
    starters = F.starter_features(team_games, goalies) if not goalies.empty else None
    # player models also see the market's implied goals (stored nightly, incl. today's pre-game prices)
    player_ctx = F.add_player_context(team_feats, F.implied_team_goals(games, odds), starters)
    win_probs: dict[int, float] = {}
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
        live = _live_lineups(current, skaters, rosters, ratings)
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
    return {"team_feats": player_ctx, "win_probs": win_probs, "placeholders": placeholders, "lineups": lineups}

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
        built = await asyncio.to_thread(_build_context, team_stats, games, goalies, skaters, rosters, odds, team_mtime)
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

async def _load_game_mates(db: AsyncSession, game_ids: list[int]) -> pd.DataFrame:
    """Every skater's ice time, PP time, shots and xG in `game_ids` (the inputs of `features.skater_shares`)."""
    from sqlalchemy import select
    from app.models import SkaterGameLog as S, Player
    stmt = (select(S.game_id, S.player_team_tricode.label("team"), S.player_id, Player.position, S.toi, S.pp_toi,
                   S.shots_on_goal, S.x_goals)
            .join(Player, Player.id == S.player_id).where(S.game_id.in_(game_ids)))
    rows = (await db.execute(stmt)).mappings().all()
    return pd.DataFrame([dict(r) for r in rows], columns=["game_id", "team", "player_id", "position", "toi", "pp_toi",
                                                          "shots_on_goal", "x_goals"])

async def predict_skater(db: AsyncSession, player_id: int, team: str, game) -> dict | None:
    """Expected goals/assists/points in `game` and the chance of at least one of each. None without history."""
    bundle = load_bundle(SKATER_BUNDLE)
    logs = await load_skater_logs(db, [player_id])
    if logs.empty:
        return None
    ctx = await _team_context(db)
    upcoming = _upcoming_player_rows(logs, game, team, ctx["placeholders"])
    # deployment shares need every skater of the player's past games, not just his own rows
    uses_shares = any(c in bundle["features"] for c in F.SKATER_SHARE_COLUMNS)
    shares = F.skater_shares(await _load_game_mates(db, logs["game_id"].unique().tolist())) if uses_shares else None
    df, _ = F.skater_features(pd.concat([logs, upcoming], ignore_index=True), ctx["team_feats"],
                              league_rates=bundle["league_rates"], extra_stats=bundle.get("extra_stats", ()),
                              shares=shares, lineups=ctx.get("lineups"))
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
    return out

# Odds API prop markets -> the model stat that settles them
PROP_STATS = {"player_goals": "goals", "player_assists": "assists", "player_points": "points",
              "player_shots_on_goal": "shots_on_goal", "player_total_saves": "saves",
              "player_blocked_shots": "blocked_shots", "player_hits": "hits", "player_goal_scorer_anytime": "goals"}
# player_power_play_points isn't priced: the model's pp_points counts 5-on-4 time only, while books settle on every
# power-play strength (5-on-3, 4-on-3, ...), so it would show false under edges

def prop_probability(expected: dict, prop_type: str, line: float, side: str) -> float | None:
    """Chance the over/under (or yes) side of a prop wins under the model's rate for that stat. Counts are Poisson,
    except stats measured to be over-dispersed (hits, blocks), which use a negative binomial with variance
    mu(1 + alpha mu). Half-point lines can't push; a whole-number line's push counts as not winning."""
    from scipy.stats import poisson, nbinom
    stat = PROP_STATS.get(prop_type)
    if stat is None or stat not in expected:
        return None
    lam, alpha = expected[stat], PROP_DISPERSION.get(stat, 0.0)
    if alpha > 0:
        n = 1 / alpha
        cdf = lambda k: nbinom.cdf(k, n, n / (n + lam))
    else:
        cdf = lambda k: poisson.cdf(k, lam)
    if side.lower() in ("over", "yes"):
        return float(1 - cdf(np.floor(line)))
    return float(cdf(np.ceil(line) - 1))
