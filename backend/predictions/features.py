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

# all-situation totals plus 5v5 score/venue-adjusted ones (from the team_game_stats table)
TEAM_STATS = ["gf", "ga", "xgf", "xga", "saf", "saa", "xgf5", "xga5", "cf5", "ca5", "gf5", "ga5"]

def build_team_games(team_stats: pd.DataFrame) -> pd.DataFrame:
    """`team_stats` has one row per (game_id, team): opponent, season, game_date, is_home and TEAM_STATS
    (NaN for upcoming games). Adds a date column and sorts each team's games chronologically."""
    out = team_stats.copy()
    out["date"] = _date(out["game_date"])
    return out.sort_values(["team", "date", "game_id"]).reset_index(drop=True)

def team_history_features(team_games: pd.DataFrame) -> pd.DataFrame:
    """Pre-game strength of each team in each game, keyed by (game_id, team)."""
    tg = team_games.sort_values(["team", "date", "game_id"]).reset_index(drop=True)
    feats = _prior_features(tg, "team", TEAM_STATS, prefix="team_")
    keep = [c for c in feats.columns if c.endswith(("_ewm", "_season")) or c == "team_games_season"]
    feats = feats[keep]
    pct = lambda a, b: a / (a + b)
    for window in ("ewm", "season"):
        f = lambda s: feats[f"team_{s}_{window}"]
        feats[f"team_xg_pct_{window}"] = pct(f("xgf"), f("xga"))
        feats[f"team_g_pct_{window}"] = pct(f("gf"), f("ga"))
        # goaltending + finishing luck: actual goals against minus expected
        feats[f"team_gsax_{window}"] = f("xga") - f("ga")
        # even strength, adjusted for score effects and venue: the steadiest read of team quality
        feats[f"team_xg5_pct_{window}"] = pct(f("xgf5"), f("xga5"))
        feats[f"team_cf5_pct_{window}"] = pct(f("cf5"), f("ca5"))
    feats["team_rest_days"] = _rest_days(tg, "team")
    # second night of a back-to-back; a step the linear model can't get from rest days alone
    feats["team_back_to_back"] = (feats["team_rest_days"] <= 1).astype(float)
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

# ---------- starting goalies ----------

GOALIE_PRIOR_HOURS = 25.0     # shrink a goalie's GSAx rate toward league average with ~25 games of prior
STARTER_LOOKBACK = 10         # team games used to guess the starter

def actual_starters(goalies: pd.DataFrame) -> pd.DataFrame:
    """The goalie who played the most in each team-game."""
    s = goalies.loc[goalies["toi"] == goalies.groupby(["game_id", "team"])["toi"].transform("max")]
    return s.drop_duplicates(["game_id", "team"])[["game_id", "team", "player_id"]]

def projected_starters(team_games: pd.DataFrame, starters: pd.DataFrame) -> pd.DataFrame:
    """A pre-game guess of each team's starter from the schedule alone: the goalie with the most starts in the
    team's last 10 games, or the most-used other goalie on the second night of a back-to-back.
    Right ~65% of the time; using the real starter instead only improved the win model marginally."""
    tg = team_games[["game_id", "team", "date"]].merge(starters, on=["game_id", "team"], how="left")
    tg = tg.sort_values(["team", "date", "game_id"])
    out = []
    for team, grp in tg.groupby("team", sort=False):
        history: list = []
        prev_date, prev_starter = None, None
        for gid, date, starter in zip(grp["game_id"], grp["date"], grp["player_id"]):
            counts = pd.Series(history[-STARTER_LOOKBACK:]).value_counts() if history else None
            pick = counts.index[0] if counts is not None else np.nan
            if prev_date is not None and (date - prev_date).days <= 1 and pick == prev_starter and len(counts) > 1:
                pick = counts.index[1]
            out.append((gid, team, pick))
            if not pd.isna(starter):
                history.append(starter)
            prev_date, prev_starter = date, starter
    return pd.DataFrame(out, columns=["game_id", "team", "player_id"])

def goalie_quality(goalies: pd.DataFrame) -> pd.DataFrame:
    """Each goalie's goals saved above expected per 60 (shrunk) *after* each game date; looked up strictly
    before a game it is that goalie's pre-game quality."""
    g = goalies.assign(date=_date(goalies["game_date"]), gsax=goalies["x_goals_against"] - goalies["goals_against"])
    g = g.sort_values(["player_id", "date", "game_id"])
    by = g.groupby("player_id", sort=False)
    out = pd.DataFrame({"player_id": g["player_id"], "date": g["date"]})
    out["gsax60"] = by["gsax"].cumsum() / (by["toi"].cumsum() / 3600 + GOALIE_PRIOR_HOURS)
    return out.drop_duplicates(["player_id", "date"], keep="last").sort_values("date")

def starter_features(team_games: pd.DataFrame, goalies: pd.DataFrame) -> pd.DataFrame:
    """Projected starter's pre-game quality for every (game_id, team) in `team_games`."""
    picks = projected_starters(team_games, actual_starters(goalies))
    picks = picks.merge(team_games[["game_id", "team", "date"]], on=["game_id", "team"]).dropna(subset=["player_id"])
    picks["player_id"] = picks["player_id"].astype("int64")
    looked = pd.merge_asof(picks.sort_values("date"), goalie_quality(goalies), on="date", by="player_id",
                           allow_exact_matches=False)
    return looked[["game_id", "team", "gsax60"]].rename(columns={"gsax60": "starter_gsax60"})

# ---------- roster ratings ----------
# Team averages only learn about a new player after he has played for the team; a roster rating sums each
# expected skater's own career-based rating, so trades, injuries and offseason moves count from day one.

ROSTER_PRIOR_HOURS = 8.0      # shrink a skater's per-60 rates toward his position's league rate (~30 games)
ROSTER_EWM_HALFLIFE = 10      # games, for expected ice time and on-ice xG share
LINEUP_SIZE = 18              # dressed skaters

def skater_ratings(skaters: pd.DataFrame) -> pd.DataFrame:
    """Each skater's rating *after* each game he played (cumulative, so it follows him across teams).
    Looked up strictly before a game date, it's his pre-game rating. Expected per-game contributions are
    shrunk per-60 rates x expected ice time."""
    df = skaters.assign(date=_date(skaters["game_date"]), is_defense=(skaters["position"] == "D").astype(float))
    df = df.sort_values(["player_id", "date", "game_id"]).reset_index(drop=True)
    by = df.groupby("player_id", sort=False)
    hours = by["toi"].cumsum() / 3600
    out = pd.DataFrame({"player_id": df["player_id"], "date": df["date"]})
    # the league rate each position shrinks toward, as of each date (never using later games)
    daily = df.groupby(["is_defense", "date"])[["game_score", "points", "toi"]].sum().groupby(level=0).cumsum()
    league = df[["is_defense", "date"]].merge(daily.reset_index(), on=["is_defense", "date"], how="left")
    for stat in ("game_score", "points"):
        league_rate = (league[stat] / (league["toi"] / 3600)).to_numpy()
        out[f"{stat}_per60"] = (by[stat].cumsum() + ROSTER_PRIOR_HOURS * league_rate) / (hours + ROSTER_PRIOR_HOURS)
    out["exp_toi"] = by["toi"].transform(lambda s: s.ewm(halflife=ROSTER_EWM_HALFLIFE).mean()) / 3600
    out["on_ice_xg_pct"] = by["on_ice_x_goals_percentage"].transform(lambda s: s.ewm(halflife=ROSTER_EWM_HALFLIFE).mean())
    out["exp_game_score"] = out["game_score_per60"] * out["exp_toi"]
    out["exp_points"] = out["points_per60"] * out["exp_toi"]
    return out.drop_duplicates(["player_id", "date"], keep="last").sort_values("date")

def expected_lineups(skaters: pd.DataFrame, team_games: pd.DataFrame) -> pd.DataFrame:
    """The skaters expected to dress for each (game_id, team) in `team_games`: whoever played the team's previous
    game that season. A team's first game of a season uses that game's actual lineup (the opening-night roster
    is known beforehand); upcoming games with no previous game this season need the current roster instead."""
    played = skaters[["game_id", "team", "player_id"]]
    tg = team_games[["game_id", "team", "season", "date"]].sort_values(["team", "date", "game_id"])
    has_lineup = tg["game_id"].isin(played["game_id"])
    prev = tg.assign(src=tg["game_id"].where(has_lineup)).groupby(["team", "season"])["src"].transform(
        lambda s: s.shift(1).ffill())
    tg = tg.assign(src=prev.fillna(tg["game_id"].where(has_lineup)))
    lineups = tg.dropna(subset=["src"]).astype({"src": "int64"}).merge(
        played.rename(columns={"game_id": "src"}), on=["src", "team"])
    return lineups[["game_id", "team", "date", "player_id"]]

def roster_ratings(lineups: pd.DataFrame, ratings: pd.DataFrame) -> pd.DataFrame:
    """Sums each expected lineup's pre-game skater ratings into team roster ratings, keyed by (game_id, team)."""
    looked = pd.merge_asof(lineups.sort_values("date"), ratings, on="date", by="player_id", allow_exact_matches=False)
    # keep the 18 skaters with the most expected ice time (a previous game can list extra call-ups)
    looked = looked.sort_values("exp_toi", ascending=False).groupby(["game_id", "team"]).head(LINEUP_SIZE)
    weighted = looked.assign(w_xg=looked["on_ice_xg_pct"] * looked["exp_toi"])
    agg = weighted.groupby(["game_id", "team"]).agg(
        roster_game_score=("exp_game_score", "sum"), roster_points=("exp_points", "sum"),
        _w_xg=("w_xg", "sum"), _toi=("exp_toi", "sum"), roster_n=("player_id", "count")).reset_index()
    agg["roster_xg_pct"] = agg["_w_xg"] / agg["_toi"]
    return agg.drop(columns=["_w_xg", "_toi"])

def latest_skater_ratings(ratings: pd.DataFrame) -> pd.DataFrame:
    """Each skater's most recent rating (saved with the team model so live predictions don't reload careers)."""
    return ratings.sort_values("date").drop_duplicates("player_id", keep="last").reset_index(drop=True)

def roster_lineups(rosters: pd.DataFrame, games: pd.DataFrame, ratings: pd.DataFrame) -> pd.DataFrame:
    """Expected lineups from current rosters (player_id, team, position) for `games` (game_id, team, date): the
    skaters with the most expected ice time, 12 forwards and 6 defensemen. Used before a team's first game."""
    r = rosters[rosters["position"] != "G"].merge(ratings[["player_id", "exp_toi"]], on="player_id", how="left")
    r["is_defense"] = r["position"] == "D"
    r = r.sort_values("exp_toi", ascending=False)
    top = pd.concat([r[~r["is_defense"]].groupby("team").head(12), r[r["is_defense"]].groupby("team").head(6)])
    return games[["game_id", "team", "date"]].merge(top[["team", "player_id"]], on="team")

# ---------- team model frame ----------

TEAM_MODEL_SIDE_FEATURES = ["team_xg_pct_ewm", "team_xg_pct_season", "team_g_pct_ewm", "team_gsax_ewm",
                            "team_xg5_pct_ewm", "team_xg5_pct_season", "team_games_season", "team_rest_days",
                            "team_back_to_back"]

def build_team_model_frame(games: pd.DataFrame, team_feats: pd.DataFrame, side_feats: list[pd.DataFrame] = ()) -> pd.DataFrame:
    """One row per game from the home team's perspective, with home_*, away_* and difference features.
    `games` needs id, season, date, home/away tri codes, home/away scores (NaN for unplayed games).
    `side_feats` are extra per-(game_id, team) frames (starting goalie, roster ratings) joined for both sides."""
    elo = elo_ratings(games)
    df = games.rename(columns={"id": "game_id"}).merge(elo, on="game_id", how="left")
    side = team_feats[["game_id", "team"] + TEAM_MODEL_SIDE_FEATURES]
    for extra in side_feats:
        side = side.merge(extra, on=["game_id", "team"], how="left")
    for prefix, col in (("home_", "home_team_tri_code"), ("away_", "away_team_tri_code")):
        renamed = side.rename(columns={c: prefix + c.removeprefix("team_") for c in side.columns if c not in ("game_id", "team")})
        df = df.merge(renamed.rename(columns={"team": col}), on=["game_id", col], how="left")
    df["elo_diff"] = df["home_elo"] + 35.0 - df["away_elo"]
    df["elo_prob"] = 1.0 / (1.0 + 10 ** (-df["elo_diff"] / 400.0))
    for stat in ("xg_pct_ewm", "xg_pct_season", "g_pct_ewm", "gsax_ewm", "rest_days", "xg5_pct_ewm", "xg5_pct_season",
                 "starter_gsax60", "roster_game_score", "roster_points", "roster_xg_pct"):
        if f"home_{stat}" in df:
            df[f"diff_{stat}"] = df[f"home_{stat}"] - df[f"away_{stat}"]
    df["home_win"] = np.where(df["home_score"].notna(), (df["home_score"] > df["away_score"]).astype(float), np.nan)
    return df

# logistic regression inputs; on four test seasons this beat an XGBoost model and a blend of the two
TEAM_FEATURE_COLUMNS = ["elo_diff", "diff_xg_pct_ewm", "diff_xg_pct_season", "diff_g_pct_ewm", "diff_gsax_ewm",
                        "diff_rest_days", "home_rest_days", "away_rest_days", "diff_xg5_pct_season", "diff_xg5_pct_ewm",
                        "diff_starter_gsax60", "diff_roster_game_score", "diff_roster_points", "diff_roster_xg_pct",
                        "home_back_to_back", "away_back_to_back"]

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
