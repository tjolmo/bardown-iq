"""Feature engineering shared by training and live prediction.

Every feature for a game is built only from games played *before* it, so the same code produces
training rows (one per past game) and live rows (an appended upcoming game whose stats are unknown).
XGBoost handles missing values natively, so early-season or debut rows keep NaNs instead of being dropped.
"""
import numpy as np
import pandas as pd

EWM_HALFLIFE = 10       # games; long enough to smooth noise, short enough to follow form
RECENT_WINDOW = 5
SHRINK_GAMES = 25       # prior strength (in games) when shrinking a player's career rate toward league average
MAX_REST_DAYS = 7

# ---------- generic helpers ----------

def _date(col: pd.Series) -> pd.Series:
    return pd.to_datetime(col.astype("int64").astype(str), format="%Y%m%d")

def _prior_features(df: pd.DataFrame, key: str, cols: list[str], prefix: str = "") -> pd.DataFrame:
    """For each row, summaries of the same entity's *previous* rows: last-5 mean, EWM, season-to-date mean,
    career mean, plus prior game counts. `df` must be sorted chronologically within `key`."""
    out = pd.DataFrame(index=df.index)
    by_key = df.groupby(key, sort=False)
    prev = by_key[cols].shift(1)
    prev_by_key = prev.groupby(df[key], sort=False)

    recent = prev_by_key.rolling(RECENT_WINDOW, min_periods=1).mean().reset_index(level=0, drop=True)
    ewm = prev_by_key.ewm(halflife=EWM_HALFLIFE, ignore_na=True).mean().reset_index(level=0, drop=True)
    # count only games where the stat was recorded, so appended upcoming games (stats unknown) don't dilute the means
    played = df[cols].notna().astype(int)
    career_counts = played.groupby(df[key], sort=False).cumsum() - played
    career_mean = prev.fillna(0.0).groupby(df[key], sort=False).cumsum() / career_counts.replace(0, np.nan)

    season_keys = [df[key], df["season"]]
    season_prev = df.groupby(season_keys, sort=False)[cols].shift(1)
    season_counts = played.groupby(season_keys, sort=False).cumsum() - played
    season_mean = season_prev.fillna(0.0).groupby(season_keys, sort=False).cumsum() / season_counts.replace(0, np.nan)
    career_n, season_n = career_counts[cols[0]], season_counts[cols[0]]

    for c in cols:
        out[f"{prefix}{c}_l5"] = recent[c]
        out[f"{prefix}{c}_ewm"] = ewm[c]
        out[f"{prefix}{c}_season"] = season_mean[c]
        out[f"{prefix}{c}_career"] = career_mean[c]
    out[f"{prefix}games_career"] = career_n
    out[f"{prefix}games_season"] = season_n
    out[f"{prefix}games_l5"] = np.minimum(career_n, RECENT_WINDOW)
    return out

def _rest_days(df: pd.DataFrame, key: str) -> pd.Series:
    days = df.groupby(key, sort=False)["date"].diff().dt.days
    # first game of the season (or of a career) counts as fully rested
    new_season = df.groupby(key, sort=False)["season"].shift(1) != df["season"]
    return days.where(~new_season, MAX_REST_DAYS).clip(upper=MAX_REST_DAYS).fillna(MAX_REST_DAYS)

LEAGUE_TREND_HALFLIFE_DAYS = 45   # game days

def league_trend(df: pd.DataFrame, target: str) -> pd.Series:
    """League-wide average of `target` over recent game days, using only days before each row's date.
    Used as the Poisson base margin so the models learn *relative* rates and follow league-wide drift
    (e.g. shots per game falling from ~30 to ~27 between 2021 and 2025) instead of baking in old levels."""
    daily = df.groupby("date")[target].mean().sort_index()
    trend = daily.shift(1).ewm(halflife=LEAGUE_TREND_HALFLIFE_DAYS, ignore_na=True).mean()
    trend = trend.fillna(daily.expanding().mean().shift(1)).bfill()
    return df["date"].map(trend)

def latest_league_trend(df: pd.DataFrame, target: str) -> float:
    """The trend value for a game played after every row in `df` (for live predictions)."""
    daily = df.groupby("date")[target].mean().sort_index()
    return float(daily.ewm(halflife=LEAGUE_TREND_HALFLIFE_DAYS, ignore_na=True).mean().iloc[-1])

# ---------- team level ----------

TEAM_STATS = ["gf", "ga", "xgf", "xga", "saf", "saa", "hdf", "hda"]

def build_team_games(team_for: pd.DataFrame) -> pd.DataFrame:
    """`team_for` has one row per (game_id, team) with that team's offensive totals (gf, xgf, saf, hdf)
    plus opponent, season, game_date, is_home. Adds the matching "against" columns from the opponent's row."""
    against = team_for[["game_id", "team", "gf", "xgf", "saf", "hdf"]].rename(
        columns={"team": "opponent", "gf": "ga", "xgf": "xga", "saf": "saa", "hdf": "hda"}
    )
    out = team_for.merge(against, on=["game_id", "opponent"], how="left")
    out["date"] = _date(out["game_date"])
    return out.sort_values(["team", "date", "game_id"]).reset_index(drop=True)

def team_history_features(team_games: pd.DataFrame) -> pd.DataFrame:
    """Pre-game strength of each team in each game, keyed by (game_id, team)."""
    tg = team_games.sort_values(["team", "date", "game_id"]).reset_index(drop=True)
    feats = _prior_features(tg, "team", TEAM_STATS, prefix="team_")
    keep = [c for c in feats.columns if c.endswith(("_ewm", "_season")) or c == "team_games_season"]
    feats = feats[keep]
    for window in ("ewm", "season"):
        xgf, xga = feats[f"team_xgf_{window}"], feats[f"team_xga_{window}"]
        gf, ga = feats[f"team_gf_{window}"], feats[f"team_ga_{window}"]
        feats[f"team_xg_pct_{window}"] = xgf / (xgf + xga)
        feats[f"team_g_pct_{window}"] = gf / (gf + ga)
        # goaltending + finishing luck: actual goals against minus expected
        feats[f"team_gsax_{window}"] = feats[f"team_xga_{window}"] - feats[f"team_ga_{window}"]
    feats["team_rest_days"] = _rest_days(tg, "team")
    feats["game_id"] = tg["game_id"].values
    feats["team"] = tg["team"].values
    return feats

def elo_ratings(games: pd.DataFrame, k: float = 8.0, home_adv: float = 35.0, carry: float = 0.7) -> pd.DataFrame:
    """Pre-game Elo for every game in `games` (id, season, date, home/away tri code, scores).
    Games without a final score get pre-game ratings but don't update them, so upcoming games can be rated.
    Margin-of-victory multiplier as in FiveThirtyEight's NHL model; ratings regress toward 1500 each season."""
    g = games.sort_values(["date", "id"])
    ratings: dict[str, float] = {}
    season_of: dict[str, int] = {}
    rows = []
    for gid, season, home, away, hs, as_ in zip(g["id"], g["season"], g["home_team_tri_code"],
                                                g["away_team_tri_code"], g["home_score"], g["away_score"]):
        for t in (home, away):
            if t not in ratings:
                ratings[t], season_of[t] = 1500.0, season
            elif season_of[t] != season:
                ratings[t] = 1500.0 + carry * (ratings[t] - 1500.0)
                season_of[t] = season
        rh, ra = ratings[home], ratings[away]
        rows.append((gid, rh, ra))
        if pd.isna(hs) or pd.isna(as_):
            continue
        p_home = 1.0 / (1.0 + 10 ** (-(rh + home_adv - ra) / 400.0))
        result = 1.0 if hs > as_ else 0.0
        margin = abs(hs - as_)
        winner_diff = (rh + home_adv - ra) if result == 1.0 else (ra - rh - home_adv)
        mult = np.log(margin + 1) * 2.2 / (winner_diff * 0.001 + 2.2)
        delta = k * mult * (result - p_home)
        ratings[home] = rh + delta
        ratings[away] = ra - delta
    return pd.DataFrame(rows, columns=["game_id", "home_elo", "away_elo"])

TEAM_MODEL_SIDE_FEATURES = [
    "team_xgf_ewm", "team_xga_ewm", "team_gf_ewm", "team_ga_ewm", "team_saf_ewm", "team_saa_ewm",
    "team_xg_pct_ewm", "team_xg_pct_season", "team_g_pct_ewm", "team_g_pct_season",
    "team_gsax_ewm", "team_gsax_season", "team_games_season", "team_rest_days",
]

def build_team_model_frame(games: pd.DataFrame, team_feats: pd.DataFrame) -> pd.DataFrame:
    """One row per game from the home team's perspective, with home_*, away_* and difference features.
    `games` needs id, season, date, home/away tri codes, home/away scores (NaN for unplayed games)."""
    elo = elo_ratings(games)
    df = games.rename(columns={"id": "game_id"}).merge(elo, on="game_id", how="left")
    side = team_feats[["game_id", "team"] + TEAM_MODEL_SIDE_FEATURES]
    for prefix, col in (("home_", "home_team_tri_code"), ("away_", "away_team_tri_code")):
        renamed = side.rename(columns={c: prefix + c.removeprefix("team_") for c in TEAM_MODEL_SIDE_FEATURES})
        df = df.merge(renamed.rename(columns={"team": col}), on=["game_id", col], how="left")
    df["elo_diff"] = df["home_elo"] + 35.0 - df["away_elo"]
    df["elo_prob"] = 1.0 / (1.0 + 10 ** (-df["elo_diff"] / 400.0))
    for stat in ("xg_pct_ewm", "xg_pct_season", "g_pct_ewm", "gsax_ewm", "rest_days"):
        df[f"diff_{stat}"] = df[f"home_{stat}"] - df[f"away_{stat}"]
    df["home_win"] = np.where(df["home_score"].notna(), (df["home_score"] > df["away_score"]).astype(float), np.nan)
    return df

TEAM_FEATURE_COLUMNS = (
    ["home_elo", "away_elo", "elo_diff"]
    + ["home_" + c.removeprefix("team_") for c in TEAM_MODEL_SIDE_FEATURES]
    + ["away_" + c.removeprefix("team_") for c in TEAM_MODEL_SIDE_FEATURES]
    + ["diff_xg_pct_ewm", "diff_xg_pct_season", "diff_g_pct_ewm", "diff_gsax_ewm", "diff_rest_days"]
)

# ---------- opponent / own-team context shared by player models ----------

CONTEXT_TEAM_COLUMNS = ["team_xgf_ewm", "team_xga_ewm", "team_gf_ewm", "team_ga_ewm",
                        "team_saf_ewm", "team_saa_ewm", "team_xg_pct_season", "team_gsax_season"]

def attach_team_context(players: pd.DataFrame, team_feats: pd.DataFrame) -> pd.DataFrame:
    """Joins the player's own team (own_*) and the opponent (opp_*) pre-game team strength onto player rows."""
    tf = team_feats[["game_id", "team"] + CONTEXT_TEAM_COLUMNS]
    own = tf.rename(columns={c: "own_" + c.removeprefix("team_") for c in CONTEXT_TEAM_COLUMNS})
    opp = tf.rename(columns={c: "opp_" + c.removeprefix("team_") for c in CONTEXT_TEAM_COLUMNS})
    out = players.merge(own, on=["game_id", "team"], how="left")
    out = out.merge(opp.rename(columns={"team": "opponent"}), on=["game_id", "opponent"], how="left")
    return out

OWN_CONTEXT = ["own_" + c.removeprefix("team_") for c in CONTEXT_TEAM_COLUMNS]
OPP_CONTEXT = ["opp_" + c.removeprefix("team_") for c in CONTEXT_TEAM_COLUMNS]

# ---------- skaters ----------

SKATER_STATS = ["goals", "assists", "primary_assists", "secondary_assists", "points", "x_goals", "toi",
                "shot_attempts", "high_danger_shots", "on_ice_x_goals_percentage", "game_score"]
SKATER_RATE_STATS = ["goals", "assists", "points", "x_goals", "shot_attempts"]

def skater_features(skaters: pd.DataFrame, team_feats: pd.DataFrame, league_rates: dict | None = None,
                    extra_stats: tuple[str, ...] = ()) -> tuple[pd.DataFrame, dict]:
    """`skaters`: one row per (player, game) with DB game-log columns plus position.
    Returns the feature frame and the league per-60 rates used for shrinkage (so live prediction reuses them)."""
    df = skaters.copy()
    df["assists"] = df["primary_assists"] + df["secondary_assists"]
    df["date"] = _date(df["game_date"])
    df = df.sort_values(["player_id", "date", "game_id"]).reset_index(drop=True)
    df["is_defense"] = (df["position"] == "D").astype(float)

    feats = _prior_features(df, "player_id", SKATER_STATS + list(extra_stats))
    df = pd.concat([df, feats], axis=1)
    df["rest_days"] = _rest_days(df, "player_id")
    df["back_to_back"] = (df["rest_days"] <= 1).astype(float)

    # career per-60 rates shrunk toward the position's league rate: stable for veterans, sane for rookies
    by_player = df.groupby("player_id", sort=False)
    toi_sum = by_player["toi"].shift(1).groupby(df["player_id"], sort=False).cumsum().fillna(0.0)
    if league_rates is None:
        league_rates = {}
        for pos, grp in df.groupby("is_defense"):
            hours = grp["toi"].sum() / 3600.0
            league_rates[float(pos)] = {s: float(grp[s].sum() / hours) for s in SKATER_RATE_STATS}
    prior_hours = SHRINK_GAMES * df["is_defense"].map({1.0: 22 * 60, 0.0: 15 * 60}).astype(float) / 3600.0
    for s in SKATER_RATE_STATS:
        stat_sum = by_player[s].shift(1).groupby(df["player_id"], sort=False).cumsum().fillna(0.0)
        league = df["is_defense"].map({k: v[s] for k, v in league_rates.items()}).astype(float)
        rate = (stat_sum + prior_hours * league) / (toi_sum / 3600.0 + prior_hours)
        df[f"{s}_per60_shrunk"] = rate
        # expected count this game = talent rate x expected ice time
        df[f"exp_{s}"] = rate * df["toi_ewm"].fillna(df["is_defense"].map({1.0: 22 * 60, 0.0: 15 * 60})) / 3600.0

    df = attach_team_context(df, team_feats)
    return df, league_rates

SKATER_FEATURE_COLUMNS = (
    [f"{s}_{w}" for s in SKATER_STATS for w in ("l5", "ewm", "season", "career")]
    + ["games_career", "games_season", "games_l5"]
    + [f"{s}_per60_shrunk" for s in SKATER_RATE_STATS] + [f"exp_{s}" for s in SKATER_RATE_STATS]
    + ["is_home", "is_defense", "rest_days", "back_to_back"]
    + OWN_CONTEXT + OPP_CONTEXT
)

# the original model's 10 inputs, kept so the old setup can be benchmarked on identical rows
LEGACY_SKATER_FEATURE_COLUMNS = ["x_goals_l5", "toi_l5", "game_score_l5", "shot_attempts_l5",
                                 "high_danger_shots_l5", "on_ice_x_goals_percentage_l5",
                                 "primary_assists_l5", "goals_l5", "points_l5", "is_home"]

# ---------- goalies ----------

GOALIE_STATS = ["goals_against", "x_goals_against", "sog", "x_sog", "toi", "gsax", "save_pct",
                "flurry_adjusted_x_goals", "high_danger_x_goals", "high_danger_shots", "rebounds", "x_rebounds"]

def goalie_features(goalies: pd.DataFrame, team_feats: pd.DataFrame) -> pd.DataFrame:
    df = goalies.copy()
    df["gsax"] = df["x_goals_against"] - df["goals_against"]
    df["save_pct"] = np.where(df["sog"] > 0, 1 - df["goals_against"] / df["sog"].where(df["sog"] > 0), np.nan)
    df["date"] = _date(df["game_date"])
    df = df.sort_values(["player_id", "date", "game_id"]).reset_index(drop=True)
    feats = _prior_features(df, "player_id", GOALIE_STATS)
    df = pd.concat([df, feats], axis=1)
    df["rest_days"] = _rest_days(df, "player_id")
    df["back_to_back"] = (df["rest_days"] <= 1).astype(float)
    return attach_team_context(df, team_feats)

GOALIE_FEATURE_COLUMNS = (
    [f"{s}_{w}" for s in GOALIE_STATS for w in ("l5", "ewm", "season", "career")]
    + ["games_career", "games_season", "games_l5", "is_home", "rest_days", "back_to_back"]
    + OWN_CONTEXT + OPP_CONTEXT
)

LEGACY_GOALIE_FEATURE_COLUMNS = ["x_goals_against_l5", "goals_against_l5", "sog_l5", "flurry_adjusted_x_goals_l5",
                                 "high_danger_x_goals_l5", "x_sog_l5", "high_danger_shots_l5", "rebounds_l5",
                                 "x_rebounds_l5", "is_home"]
