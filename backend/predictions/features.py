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

# ---------- standings ----------
# Late in a season, teams that have (nearly) clinched or been eliminated play differently (resting players,
# call-ups, tanking). The flags use only games before each date, plus the known schedule of games remaining.

_EAST_2008 = {"ATL": ["NJD", "NYI", "NYR", "PHI", "PIT"], "NE": ["BOS", "BUF", "MTL", "OTT", "TOR"],
              "SE": ["ATL", "CAR", "FLA", "TBL", "WSH"]}
_WEST_2008 = {"CEN": ["CHI", "CBJ", "DET", "NSH", "STL"], "NW": ["CGY", "COL", "EDM", "MIN", "VAN"],
              "PAC": ["ANA", "DAL", "LAK", "PHX", "SJS"]}
_METRO = ["CAR", "CBJ", "NJD", "NYI", "NYR", "PHI", "PIT", "WSH"]
_ATLANTIC = ["BOS", "BUF", "DET", "FLA", "MTL", "OTT", "TBL", "TOR"]
_CENTRAL_2013 = ["CHI", "COL", "DAL", "MIN", "NSH", "STL", "WPG"]
# (first season, last season, playoff format, {conference: {division: teams}}), checked against NHL API standings
ALIGNMENTS = [
    (2008, 2010, "conf8", {"E": _EAST_2008, "W": _WEST_2008}),
    (2011, 2012, "conf8", {"E": {**_EAST_2008, "SE": ["WPG", "CAR", "FLA", "TBL", "WSH"]}, "W": _WEST_2008}),
    (2013, 2019, "wildcard", {"E": {"M": _METRO, "A": _ATLANTIC},
                              "W": {"C": _CENTRAL_2013, "P": ["ANA", "ARI", "PHX", "CGY", "EDM", "LAK", "SJS", "VAN", "VGK"]}}),
    # 2020-21: four one-off divisions, the top four of each made the playoffs
    (2020, 2020, "div4", {"N": {"N": ["CGY", "EDM", "MTL", "OTT", "TOR", "VAN", "WPG"]},
                          "E": {"E": ["BOS", "BUF", "NJD", "NYI", "NYR", "PHI", "PIT", "WSH"]},
                          "C": {"C": ["CAR", "CBJ", "CHI", "DAL", "DET", "FLA", "NSH", "TBL"]},
                          "W": {"W": ["ANA", "ARI", "COL", "LAK", "MIN", "SJS", "STL", "VGK"]}}),
    (2021, 9999, "wildcard", {"E": {"M": _METRO, "A": _ATLANTIC},
                              "W": {"C": ["ARI", "UTA"] + _CENTRAL_2013, "P": ["ANA", "CGY", "EDM", "LAK", "SEA", "SJS", "VAN", "VGK"]}}),
]

def _alignment(season: int) -> tuple[str, dict]:
    return next((fmt, confs) for first, last, fmt, confs in ALIGNMENTS if first <= season <= last)

STANDINGS_COLUMNS = ["team_clinched", "team_eliminated"]

def standings_flags(games: pd.DataFrame) -> pd.DataFrame:
    """Per (game_id, team): clinched / eliminated at the start of the game's date, by max-points-remaining
    arithmetic within the team's standings pool (conference; division in 2020-21, with 4 spots instead of 8).
    Points are 2 per win with no overtime-loss point: the stored scores don't say which games went to overtime, and
    this wins-only version (it flips a little earlier, a softer "all but clinched / eliminated") also tested better.
    Remaining games come from the schedule in `games` (id, season, date, home/away tri codes, scores NaN until final).
    Playoff games get the final regular-season flags."""
    out = []
    regular = games[games["id"] // 10000 % 100 == 2]
    for season, sg in regular.groupby("season"):
        fmt, confs = _alignment(int(season))
        spots = 4 if fmt == "div4" else 8
        rows = pd.concat([pd.DataFrame({"game_id": sg["id"], "date": sg["date"], "team": sg[f"{s}_team_tri_code"],
                                        "won": sg[f"{s}_score"] > sg[f"{o}_score"], "played": sg["home_score"].notna()})
                          for s, o in (("home", "away"), ("away", "home"))])
        rows["pts"] = 2 * (rows["won"] & rows["played"])
        scheduled = rows.groupby("team").size()
        daily = rows.pivot_table(index="date", columns="team", values=["pts", "played"], aggfunc="sum", fill_value=0)
        # standings at the start of each date, plus a row (date -1) after the last one for the playoffs
        cum = daily.cumsum()
        before = pd.concat([cum.shift(1, fill_value=0), cum.iloc[[-1]].set_axis([-1])])
        pts, gp = before["pts"].astype(float), before["played"].astype(float)
        max_pts = pts + 2 * (scheduled.reindex(pts.columns) - gp).clip(lower=0)
        flags = []
        for divisions in confs.values():
            pool = [t for ts in divisions.values() for t in ts if t in pts.columns]
            p, m = pts[pool].to_numpy(), max_pts[pool].to_numpy()
            # [date, team, other]: clinched when fewer than `spots` other teams can still reach the team's points
            reach = (m[:, None, :] >= p[:, :, None]).sum(2) - 1
            # eliminated when `spots` other teams already have more points than the team can reach
            ahead = (p[:, None, :] > m[:, :, None]).sum(2)
            flags.append(pd.DataFrame({"date": np.repeat(pts.index.to_numpy(), len(pool)), "team": np.tile(pool, len(pts)),
                                       "team_clinched": (reach < spots).ravel().astype(float),
                                       "team_eliminated": (ahead >= spots).ravel().astype(float)}))
        flags = pd.concat(flags, ignore_index=True)
        out.append(rows[["game_id", "date", "team"]].merge(flags, on=["date", "team"], how="left").drop(columns="date"))
        final = flags[flags["date"] == -1].drop(columns="date")
        playoffs = games[(games["season"] == season) & (games["id"] // 10000 % 100 == 3)]
        for side in ("home_team_tri_code", "away_team_tri_code"):
            out.append(playoffs[["id", side]].rename(columns={"id": "game_id", side: "team"}).merge(final, on="team", how="left"))
    if not out:
        return pd.DataFrame(columns=["game_id", "team"] + STANDINGS_COLUMNS)
    return pd.concat(out, ignore_index=True)

# ---------- starting goalies ----------

GOALIE_PRIOR_HOURS = 25.0     # shrink a goalie's GSAx rate toward league average with ~25 games of prior
STARTER_LOOKBACK = 10         # team games used to guess the starter

# game_starters status of the goalie who actually started (NHL play-by-play first shot faced / boxscore flag, 2008 on)
ACTUAL_STATUS = "actual"

def most_ice_time(goalies: pd.DataFrame) -> pd.DataFrame:
    """The goalie who played the most in each team-game. Not the starter when the starter was pulled early: then it
    names the reliever, tying the backup to games already going badly."""
    s = goalies.loc[goalies["toi"] == goalies.groupby(["game_id", "team"])["toi"].transform("max")]
    return s.drop_duplicates(["game_id", "team"])[["game_id", "team", "player_id"]]

def true_starters(known: pd.DataFrame | None) -> pd.DataFrame:
    """Stored actual starters (game_starters rows with status "actual") as (game_id, team, player_id)."""
    if known is None or known.empty or "status" not in known:
        return pd.DataFrame({"game_id": pd.Series(dtype="int64"), "team": pd.Series(dtype=object),
                             "player_id": pd.Series(dtype="int64")})
    k = known[known["status"] == ACTUAL_STATUS].drop_duplicates(["game_id", "team"], keep="last")
    return k[["game_id", "team", "player_id"]].astype({"game_id": "int64", "player_id": "int64"}).reset_index(drop=True)

def actual_starters(goalies: pd.DataFrame, known: pd.DataFrame | None = None) -> pd.DataFrame:
    """Who started each played team-game: the stored actual starter where there is one, else the goalie with the
    most ice time (games without a stored starter; right for ~96% of team-games)."""
    toi, true = most_ice_time(goalies), true_starters(known)
    return _override_picks(toi, true) if not true.empty else toi

def starter_rows(goalies: pd.DataFrame, known: pd.DataFrame | None = None) -> pd.Series:
    """Boolean mask of `goalies` rows that are their team's starter (see actual_starters): a starter pulled in the
    first period counts, the goalie who relieved him doesn't."""
    keys = actual_starters(goalies, known).assign(_starter=True)
    flag = goalies[["game_id", "team", "player_id"]].merge(keys, on=["game_id", "team", "player_id"], how="left")["_starter"]
    return pd.Series(flag.fillna(False).astype(bool).to_numpy(), index=goalies.index)

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

# statuses in game_starters that override the schedule-based projection
KNOWN_STARTER_STATUSES = ("confirmed", "probable")

def _override_picks(base: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """`base` with the (game_id, team) rows that `new` covers replaced by `new`'s (rows not in `base` are ignored)."""
    base_keys, new_keys = (pd.MultiIndex.from_frame(df[["game_id", "team"]]) for df in (base, new))
    new = new[new_keys.isin(base_keys)]
    if new.empty:
        return base
    return pd.concat([base[~base_keys.isin(new_keys)], new[base.columns]], ignore_index=True)

def starter_picks(team_games: pd.DataFrame, goalies: pd.DataFrame, known: pd.DataFrame | None = None,
                  prefer_actual: bool = False) -> pd.DataFrame:
    """Each team-game's starter as (game_id, team, player_id, status), best information first:
    the stored actual starter for games already played (when `prefer_actual`; status "actual"), then a confirmed or
    probable starter from `known` (the game_starters table; status as stored), else the schedule projection
    ("projected"). The projection learns each team's habits from who actually started its past games (stored
    actual starters, else the goalie with the most ice time). Live games get confirmed/probable starters when
    announced, which is what an actual starter approximates."""
    picks = projected_starters(team_games, actual_starters(goalies, known)).assign(status="projected")
    if known is not None and not known.empty:
        k = known[known["status"].isin(KNOWN_STARTER_STATUSES)].drop_duplicates(["game_id", "team"], keep="last")
        picks = _override_picks(picks, k[["game_id", "team", "player_id", "status"]])
    if prefer_actual:
        picks = _override_picks(picks, true_starters(known).assign(status=ACTUAL_STATUS))
    return picks.reset_index(drop=True)

def starter_features(team_games: pd.DataFrame, goalies: pd.DataFrame, known: pd.DataFrame | None = None,
                     prefer_actual: bool = False, picks: pd.DataFrame | None = None) -> pd.DataFrame:
    """The starter's pre-game quality for every (game_id, team) in `team_games`; the starter is chosen by
    `starter_picks` (projection by default, as in the experiments) unless precomputed `picks` are passed."""
    if picks is None:
        picks = starter_picks(team_games, goalies, known, prefer_actual)
    picks = picks[["game_id", "team", "player_id"]]
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
RATING_HALFLIFE_DAYS: float | None = None   # calendar half-life of past games in the per-60 rates (None: equal weight)
# aging curve on: team model 0.6627 -> 0.6619 (2022-25), first 10 games 0.6667 -> 0.6656 (age_ratings experiment)
RATING_AGE_MODE: str | None = "aging"       # None or "aging" (see skater_ratings)
AGE_BUCKETS = (19, 37)        # integer ages pooled at the ends of the aging curve
EPOCH = pd.Timestamp("2000-01-01")

def age_years(date: pd.Series, birth_date: pd.Series) -> pd.Series:
    """Age in years (float) at `date`; NaN when the birth date is unknown."""
    return (date - pd.to_datetime(birth_date)).dt.days / 365.25

def _decayed_cumsum(values: pd.DataFrame, keys: pd.Series, day: np.ndarray, half_life: float | None,
                    exclusive: bool = False) -> pd.DataFrame:
    """Per-key running sums of `values` (rows sorted chronologically within key) through each row (or, with
    `exclusive`, over strictly earlier rows), each row j weighted 0.5 ** ((day_now - day_j) / half_life);
    plain running sums when half_life is None. Missing values count as 0."""
    values = values.astype(np.float64).fillna(0.0)
    # weight by 2**(day/H) and rescale by 2**(-day_now/H); days count from 2000, so 2**(days/H) stays finite
    w = np.power(2.0, day / half_life) if half_life else np.ones(len(values))
    summed = values.mul(w, axis=0).groupby(keys.to_numpy(), sort=False).cumsum()
    if exclusive:
        summed = summed.groupby(keys.to_numpy(), sort=False).shift(1).fillna(0.0)
    return summed.mul(1.0 / w, axis=0)

def _league_curve(df: pd.DataFrame, stats: list[str], by: list[str]) -> pd.DataFrame:
    """League per-hour rate of `stats` for each row's `by` group, using games on or before the row's date."""
    daily = df.groupby(by + ["date"])[stats + ["toi"]].sum().groupby(level=list(range(len(by)))).cumsum()
    looked = df[by + ["date"]].merge(daily.reset_index(), on=by + ["date"], how="left")
    hours = looked["toi"].to_numpy(np.float64) / 3600
    out = pd.DataFrame({s: looked[s].to_numpy(np.float64) / hours for s in stats})
    out["_hours"] = hours
    return out

def aging_deltas(df: pd.DataFrame, stats: list[str], min_hours: float = 5.0) -> pd.DataFrame:
    """Within-player aging curve ("delta method"): for each pair of consecutive seasons a skater played at least
    `min_hours` in both, the change in his per-hour rates, averaged (weighted by the harmonic mean of the two
    seasons' hours) by position and integer age in the first season. One row per (season, is_defense, age):
    the curve built only from season pairs completed before `season`, as cumulative change from AGE_BUCKETS[0]."""
    lo, hi = AGE_BUCKETS
    known = "_age_known_toi" in df
    seas = df.groupby(["player_id", "season", "is_defense"])[stats + ["toi", "_age_toi"] + (["_age_known_toi"] if known else [])].sum().reset_index()
    if known:
        seas = seas[seas["_age_known_toi"] > 0]
    seas["hours"] = seas["toi"] / 3600
    seas["age"] = np.floor(seas["_age_toi"] / (seas["_age_known_toi"] if known else seas["toi"])).clip(lo, hi)
    nxt = seas.assign(season=seas["season"] - 1)
    pairs = seas.merge(nxt, on=["player_id", "season", "is_defense"], suffixes=("", "_n"))
    pairs = pairs[(pairs["hours"] >= min_hours) & (pairs["hours_n"] >= min_hours)]
    w = 2 / (1 / pairs["hours"] + 1 / pairs["hours_n"])
    for st in stats:
        pairs[f"d_{st}"] = (pairs[f"{st}_n"] / pairs["hours_n"] - pairs[st] / pairs["hours"]) * w
    pairs["w"] = w
    rows = []
    ages = np.arange(lo, hi + 1)
    for season in sorted(df["season"].unique()):
        done = pairs[pairs["season"] + 1 < season]
        for pos in (0.0, 1.0):
            g = done[done["is_defense"] == pos].groupby("age")[[f"d_{st}" for st in stats] + ["w"]].sum().reindex(ages, fill_value=0.0)
            for st in stats:
                # per-age mean change, shrunk toward 0 with 50 weighted pairs; cumulative from the youngest age
                step = (g[f"d_{st}"] / (g["w"] + 50.0)).to_numpy()
                g[st] = np.concatenate([[0.0], np.cumsum(step)[:-1]])
            rows.append(pd.DataFrame({"season": season, "is_defense": pos, "age": ages,
                                      **{st: g[st].to_numpy() for st in stats}}))
    return pd.concat(rows, ignore_index=True)

def _curve_at(curve: pd.DataFrame, season: np.ndarray, pos: np.ndarray, age: np.ndarray, stat: str) -> np.ndarray:
    """Linear interpolation of an `aging_deltas` curve at fractional ages (NaN age gives NaN)."""
    lo, hi = AGE_BUCKETS
    a = np.clip(age, lo, hi)
    base = np.floor(np.nan_to_num(a, nan=lo)).astype(int)
    frac = np.nan_to_num(a, nan=lo) - base
    table = curve.set_index(["season", "is_defense", "age"])[stat]
    get = lambda ag: table.reindex(pd.MultiIndex.from_arrays([season, pos, np.minimum(ag, hi)])).to_numpy()
    out = get(base) * (1 - frac) + get(base + 1) * frac
    return np.where(np.isnan(age), np.nan, out)

def skater_ratings(skaters: pd.DataFrame, half_life_days: float | None = RATING_HALFLIFE_DAYS,
                   age_mode: str | None = RATING_AGE_MODE) -> pd.DataFrame:
    """Each skater's rating *after* each game he played (cumulative, so it follows him across teams).
    Looked up strictly before a game date, it's his pre-game rating. Expected per-game contributions are
    shrunk per-60 rates x expected ice time.
    `half_life_days` decays older games (calendar time). `age_mode="aging"` (needs `birth_date`) moves the data part
    of each rate along a within-player aging curve (`aging_deltas`), from the ice-time-weighted mean age of his
    games to his current age, so a 34-year-old's long career no longer vouches for his current level."""
    df = skaters.assign(date=_date(skaters["game_date"]), is_defense=(skaters["position"] == "D").astype(float))
    df = df.sort_values(["player_id", "date", "game_id"]).reset_index(drop=True)
    by = df.groupby("player_id", sort=False)
    stats = ["game_score", "points"]
    day = (df["date"] - EPOCH).dt.days.to_numpy(np.float64)
    out = pd.DataFrame({"player_id": df["player_id"], "date": df["date"]})
    # the league rate each position shrinks toward, as of each date (never using later games)
    league = _league_curve(df, stats, ["is_defense"])
    sums = df[stats + ["toi"]].astype(np.float64)
    use_age = age_mode == "aging" and "birth_date" in df
    if use_age:
        age = age_years(df["date"], df["birth_date"])
        df["_age_toi"] = sums["_age_toi"] = age.fillna(0.0).to_numpy() * sums["toi"].to_numpy()
        df["_age_known_toi"] = np.where(age.notna(), df["toi"], 0.0)   # players without a birth date stay out of the curve
    cum = _decayed_cumsum(sums, df["player_id"], day, half_life_days)
    hours = cum["toi"] / 3600
    for stat in stats:
        out[f"{stat}_per60"] = (cum[stat] + ROSTER_PRIOR_HOURS * league[stat].to_numpy()) / (hours + ROSTER_PRIOR_HOURS)
    if use_age:
        curve = aging_deltas(df, stats)
        mean_age = (cum["_age_toi"] / cum["toi"]).where(age.notna()).to_numpy()
        season, pos, now = df["season"].to_numpy(), df["is_defense"].to_numpy(), age.to_numpy()
        for stat in stats:
            shift = _curve_at(curve, season, pos, now, stat) - _curve_at(curve, season, pos, mean_age, stat)
            out[f"{stat}_per60"] += np.nan_to_num(shift) * hours / (hours + ROSTER_PRIOR_HOURS)
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
                            "team_back_to_back",
                            # offence / defence rates, for the goals model
                            "team_xgf_ewm", "team_xga_ewm", "team_gf_ewm", "team_ga_ewm", "team_xgf_season",
                            "team_xga_season", "team_xgf5_ewm", "team_xga5_ewm"]

def build_team_model_frame(games: pd.DataFrame, team_feats: pd.DataFrame, side_feats: list[pd.DataFrame] = ()) -> pd.DataFrame:
    """One row per game from the home team's perspective, with home_*, away_* and difference features.
    `games` needs id, season, date, home/away tri codes, home/away scores (NaN for unplayed games).
    `side_feats` are extra per-(game_id, team) frames (starting goalie, roster ratings) joined for both sides."""
    elo = elo_ratings(games)
    df = games.rename(columns={"id": "game_id"}).merge(elo, on="game_id", how="left")
    side = team_feats[["game_id", "team"] + TEAM_MODEL_SIDE_FEATURES].merge(standings_flags(games), on=["game_id", "team"], how="left")
    for extra in side_feats:
        side = side.merge(extra, on=["game_id", "team"], how="left")
    for prefix, col in (("home_", "home_team_tri_code"), ("away_", "away_team_tri_code")):
        renamed = side.rename(columns={c: prefix + c.removeprefix("team_") for c in side.columns if c not in ("game_id", "team")})
        df = df.merge(renamed.rename(columns={"team": col}), on=["game_id", col], how="left")
    df["elo_diff"] = df["home_elo"] + 35.0 - df["away_elo"]
    df["elo_prob"] = 1.0 / (1.0 + 10 ** (-df["elo_diff"] / 400.0))
    for stat in ("xg_pct_ewm", "xg_pct_season", "g_pct_ewm", "gsax_ewm", "rest_days", "xg5_pct_ewm", "xg5_pct_season",
                 "starter_gsax60", "roster_game_score", "roster_points", "roster_xg_pct", "clinched", "eliminated"):
        if f"home_{stat}" in df:
            df[f"diff_{stat}"] = df[f"home_{stat}"] - df[f"away_{stat}"]
    df["home_win"] = np.where(df["home_score"].notna(), (df["home_score"] > df["away_score"]).astype(float), np.nan)
    return df

# logistic regression inputs; on four test seasons this beat an XGBoost model and a blend of the two
TEAM_FEATURE_COLUMNS = ["elo_diff", "diff_xg_pct_ewm", "diff_xg_pct_season", "diff_g_pct_ewm", "diff_gsax_ewm",
                        "diff_rest_days", "home_rest_days", "away_rest_days", "diff_xg5_pct_season", "diff_xg5_pct_ewm",
                        "diff_starter_gsax60", "diff_roster_game_score", "diff_roster_points", "diff_roster_xg_pct",
                        "home_back_to_back", "away_back_to_back", "diff_clinched", "diff_eliminated"]

# ---------- goals model ----------
# Poisson regressions for each side's regulation goals. Not better than the logistic for the win (log loss
# +0.0004 on 2022-25), but its expected team goals match the market's implied goals (team-goal Poisson deviance
# 1.0613 vs 1.0610 on 2022-25), so they stand in for market-implied goals when a game has no odds.

GOALS_SIDE_COLUMNS = ["xgf_ewm", "xga_ewm", "gf_ewm", "ga_ewm", "xgf_season", "xga_season", "xgf5_ewm", "xga5_ewm"]
TEAM_GOALS_COLUMNS = TEAM_FEATURE_COLUMNS + [f"{side}_{c}" for side in ("home", "away") for c in GOALS_SIDE_COLUMNS]
MAX_GOALS = 15

def went_to_overtime(frame: pd.DataFrame, team_games: pd.DataFrame, goalies: pd.DataFrame) -> pd.Series:
    """Whether each finished regular-season game in `frame` (team model frame) was decided in overtime or a shootout.
    No stored field says so: a one-goal final is a shootout when MoneyPuck's goal counts (which leave out shootout
    goals) are tied, and an overtime goal when a goalie logged more than 60 minutes. Matches the NHL API's
    lastPeriodType on all but 8 of 4,964 regular-season overtime/shootout games in 2008-26, with no false positives. Playoff games are False."""
    home = team_games.loc[team_games["is_home"] == 1, ["game_id", "gf", "ga"]].drop_duplicates("game_id")
    if goalies.empty:
        toi = pd.DataFrame({"game_id": pd.Series(dtype="int64"), "goalie_toi": pd.Series(dtype=float)})
    else:
        toi = goalies.groupby(["game_id", "team"])["toi"].sum().groupby("game_id").max().rename("goalie_toi").reset_index()
    df = frame[["game_id", "home_score", "away_score"]].merge(home, on="game_id", how="left").merge(toi, on="game_id", how="left")
    one_goal = (df["home_score"] - df["away_score"]).abs() == 1
    regular = df["game_id"] // 10000 % 100 == 2
    return pd.Series((one_goal & regular & ((df["gf"] == df["ga"]) | (df["goalie_toi"] > 3600))).to_numpy(), index=frame.index)

def regulation_outcome_probs(lam_home, lam_away, tie_inflation: float = 1.0, ot_home_share: float = 0.5) -> tuple:
    """(P(home win incl. OT/SO), P(tied after regulation)) from independent Poisson regulation goals, with the
    diagonal scaled by `tie_inflation` (real games tie more often than independent scoring implies) and the rest
    renormalised; ties go to the home team with probability `ot_home_share`."""
    from scipy.stats import poisson
    g = np.arange(MAX_GOALS + 1)
    ph = poisson.pmf(g[None, :], np.asarray(lam_home, float)[:, None])
    pa = poisson.pmf(g[None, :], np.asarray(lam_away, float)[:, None])
    joint = ph[:, :, None] * pa[:, None, :]
    win = (joint * np.tril(np.ones((len(g), len(g))), -1)[None]).sum((1, 2))
    tie = np.einsum("nii->n", joint)
    lose = joint.sum((1, 2)) - win - tie
    tie = np.clip(tie * tie_inflation, 0.0, 1.0)
    return win * (1 - tie) / (win + lose) + ot_home_share * tie, tie

def model_team_goals(frame: pd.DataFrame, goals: dict) -> pd.DataFrame:
    """Each team's expected goals (regulation plus its share of the overtime/shootout winner, as with
    `implied_team_goals`) from the saved goals model, one row per (game_id, team) as team_implied_goals."""
    if frame.empty:
        return pd.DataFrame(columns=["game_id", "team", "team_implied_goals"])
    X = frame[goals["features"]]
    lh, la = goals["home"].predict(X), goals["away"].predict(X)
    _, tie = regulation_outcome_probs(lh, la, goals["tie_inflation"], goals["ot_home_share"])
    s = goals["ot_home_share"]
    return pd.concat([
        pd.DataFrame({"game_id": frame["game_id"], "team": frame["home_team_tri_code"], "team_implied_goals": lh + s * tie}),
        pd.DataFrame({"game_id": frame["game_id"], "team": frame["away_team_tri_code"], "team_implied_goals": la + (1 - s) * tie})],
        ignore_index=True)

# ---------- opponent / own-team context shared by player models ----------

CONTEXT_TEAM_COLUMNS = ["team_xgf_ewm", "team_xga_ewm", "team_gf_ewm", "team_ga_ewm",
                        "team_saf_ewm", "team_saa_ewm", "team_xg_pct_season", "team_gsax_season"]

# optional per-(game_id, team) columns joined onto team_feats when available (market odds, projected starter)
OPTIONAL_TEAM_COLUMNS = ["team_implied_goals", "team_starter_gsax60"]

def attach_team_context(players: pd.DataFrame, team_feats: pd.DataFrame) -> pd.DataFrame:
    """Joins the player's own team (own_*) and the opponent (opp_*) pre-game team strength onto player rows."""
    cols = CONTEXT_TEAM_COLUMNS + [c for c in OPTIONAL_TEAM_COLUMNS if c in team_feats]
    tf = team_feats[["game_id", "team"] + cols]
    own = tf.rename(columns={c: "own_" + c.removeprefix("team_") for c in cols})
    opp = tf.rename(columns={c: "opp_" + c.removeprefix("team_") for c in cols})
    out = players.merge(own, on=["game_id", "team"], how="left")
    out = out.merge(opp.rename(columns={"team": "opponent"}), on=["game_id", "opponent"], how="left")
    return out

# market-implied goals for and against, and the opposing projected starter's quality
MARKET_CONTEXT = ["own_implied_goals", "opp_implied_goals", "opp_starter_gsax60"]

def add_player_context(team_feats: pd.DataFrame, implied: pd.DataFrame, starters: pd.DataFrame | None,
                       fallback: pd.DataFrame | None = None) -> pd.DataFrame:
    """Adds market-implied goals and the projected starter's quality to team_feats for the player models
    (missing when a game has no odds or a team no goalie history; XGBoost handles the gaps).
    `fallback` (live only: the goals model's `model_team_goals`) fills implied goals for games without odds.
    Training leaves them missing: with the market available that scored best, and for games without odds a model
    trained that way did better on goals-model values than on gaps (goalie saves deviance 1.7315 vs 1.7459)."""
    tf = team_feats.merge(implied, on=["game_id", "team"], how="left")
    if fallback is not None and not fallback.empty:
        fb = tf[["game_id", "team"]].merge(fallback, on=["game_id", "team"], how="left")["team_implied_goals"]
        tf["team_implied_goals"] = tf["team_implied_goals"].fillna(pd.Series(fb.to_numpy(), index=tf.index))
    if starters is not None:
        tf = tf.merge(starters.rename(columns={"starter_gsax60": "team_starter_gsax60"}), on=["game_id", "team"], how="left")
    return tf

def implied_team_goals(games: pd.DataFrame, odds: pd.DataFrame, ot_home_share: float = 0.5) -> pd.DataFrame:
    """Each team's expected goals implied by the betting market. Finds Poisson scoring rates for home and away
    that sum to the game total and reproduce the vig-free home win probability (overtime/shootout split
    `ot_home_share`). Returns one row per (game_id, team) with team_implied_goals."""
    from scipy.stats import poisson
    df = games[["id", "home_team_tri_code", "away_team_tri_code"]].rename(columns={"id": "game_id"}).merge(
        odds[["game_id", "home_prob_novig", "total_line"]].dropna(), on="game_id")
    if df.empty:
        return pd.DataFrame(columns=["game_id", "team", "team_implied_goals"])
    total, target = df["total_line"].to_numpy(float), df["home_prob_novig"].to_numpy(float)
    goals = np.arange(16)
    def p_home(share):
        lh, la = total * share, total * (1 - share)
        ph = poisson.pmf(goals[None, :], lh[:, None])
        pa = poisson.pmf(goals[None, :], la[:, None])
        joint = ph[:, :, None] * pa[:, None, :]
        win = np.tril(np.ones((16, 16)), -1)[None]          # home goals > away goals
        tie = np.eye(16)[None]
        return (joint * win).sum((1, 2)) + ot_home_share * (joint * tie).sum((1, 2))
    lo, hi = np.full(len(df), 0.2), np.full(len(df), 0.8)
    for _ in range(40):                                     # bisection on the home share of the total
        mid = (lo + hi) / 2
        above = p_home(mid) > target
        hi, lo = np.where(above, mid, hi), np.where(above, lo, mid)
    share = (lo + hi) / 2
    home = pd.DataFrame({"game_id": df["game_id"], "team": df["home_team_tri_code"], "team_implied_goals": total * share})
    away = pd.DataFrame({"game_id": df["game_id"], "team": df["away_team_tri_code"], "team_implied_goals": total * (1 - share)})
    return pd.concat([home, away], ignore_index=True)

OWN_CONTEXT = ["own_" + c.removeprefix("team_") for c in CONTEXT_TEAM_COLUMNS]
OPP_CONTEXT = ["opp_" + c.removeprefix("team_") for c in CONTEXT_TEAM_COLUMNS]

# ---------- skaters ----------

SKATER_STATS = ["goals", "assists", "primary_assists", "secondary_assists", "points", "x_goals", "toi",
                "shot_attempts", "high_danger_shots", "on_ice_x_goals_percentage", "game_score"]
SKATER_RATE_STATS = ["goals", "assists", "points", "x_goals", "shot_attempts"]
# calendar half-life of past games in the shrunk per-60 rates; 365 days beat equal weights out of time
# (2024-25/2025-26 deviance: SOG 1.2244/1.2265 -> 1.2241/1.2253, goals/assists/points -0.0001 on average)
SKATER_RATE_HALFLIFE_DAYS: float | None = 365.0

# each game's deployment and output as a share of the player's team that game; shares survive trades and
# changing ice-time levels better than raw minutes
SKATER_SHARE_STATS = ["pp_share", "toi_rank", "sog_share", "xg_share"]
PP_SKATERS = 5

def skater_shares(skaters: pd.DataFrame) -> pd.DataFrame:
    """Per (game_id, player_id): power-play time as a share of the team's power-play time (team time = summed
    skater PP time / 5), ice-time rank among the team's forwards or defensemen (1 = most), and share of the
    team's shots on goal and xG. Needs every skater of each team-game; each value uses only that game, and the
    prior-window summaries in `skater_features` make them pre-game."""
    stats = ["toi", "pp_toi", "shots_on_goal", "x_goals"]
    df = skaters.reindex(columns=["game_id", "team", "player_id", "position"] + stats)
    df[stats] = df[stats].astype(float)
    team = df.groupby(["game_id", "team"])
    share = lambda col, scale=1.0: df[col] / (team[col].transform("sum") / scale).where(lambda s: s > 0)
    out = df[["game_id", "player_id"]].copy()
    out["pp_share"] = share("pp_toi", PP_SKATERS)
    out["toi_rank"] = df.groupby(["game_id", "team", df["position"] == "D"])["toi"].rank(ascending=False)
    out["sog_share"] = share("shots_on_goal")
    out["xg_share"] = share("x_goals")
    return out.drop_duplicates(["game_id", "player_id"])

# expected game score / points of the other skaters in the player's expected lineup
TEAMMATE_COLUMNS = ["teammates_game_score", "teammates_points"]

def rated_lineups(lineups: pd.DataFrame, ratings: pd.DataFrame) -> pd.DataFrame:
    """Expected lineups (`expected_lineups`) with each skater's pre-game rating, top 18 by expected ice time
    as in `roster_ratings`."""
    looked = pd.merge_asof(lineups.sort_values("date"), ratings, on="date", by="player_id", allow_exact_matches=False)
    looked = looked.sort_values("exp_toi", ascending=False).groupby(["game_id", "team"]).head(LINEUP_SIZE)
    return looked[["game_id", "team", "player_id", "exp_toi", "exp_game_score", "exp_points"]]

def played_lineups(skaters: pd.DataFrame, ratings: pd.DataFrame) -> pd.DataFrame:
    """`rated_lineups` for every team-game in the skater logs (training; live uses the team context's lineups)."""
    tg = skaters[["game_id", "team", "season", "game_date"]].drop_duplicates(["game_id", "team"])
    return rated_lineups(expected_lineups(skaters, tg.assign(date=_date(tg["game_date"]))), ratings)

def teammate_quality(players: pd.DataFrame, lineups: pd.DataFrame) -> pd.DataFrame:
    """Per (game_id, player_id) in `players`: summed pre-game ratings of his expected teammates, i.e. the rated
    lineup without him (or its top 17 when he isn't in it, e.g. back from injury or a call-up)."""
    stats = {"exp_game_score": "teammates_game_score", "exp_points": "teammates_points"}
    lu = lineups.sort_values("exp_toi", ascending=False)
    keys = ["game_id", "team"]
    top17 = lu.groupby(keys).head(LINEUP_SIZE - 1).groupby(keys)[list(stats)].sum()
    sums = lu.groupby(keys)[list(stats)].sum().join(top17, rsuffix="_17").reset_index()
    own = lu[keys + ["player_id"] + list(stats)].rename(columns={s: f"{s}_own" for s in stats})
    out = players[keys + ["player_id"]].drop_duplicates(["game_id", "player_id"])
    out = out.merge(sums, on=keys, how="left").merge(own, on=keys + ["player_id"], how="left")
    in_lineup = out["exp_game_score_own"].notna()
    for s, name in stats.items():
        out[name] = np.where(in_lineup, out[s] - out[f"{s}_own"], out[f"{s}_17"])
    return out[["game_id", "player_id"] + TEAMMATE_COLUMNS]

def skater_features(skaters: pd.DataFrame, team_feats: pd.DataFrame, league_rates: dict | None = None,
                    extra_stats: tuple[str, ...] = (), shares: pd.DataFrame | None = None,
                    lineups: pd.DataFrame | None = None,
                    rate_half_life_days: float | None = SKATER_RATE_HALFLIFE_DAYS) -> tuple[pd.DataFrame, dict]:
    """`skaters`: one row per (player, game) with DB game-log columns plus position.
    `shares`: `skater_shares` of every skater in these games (a player's own rows can't give team totals);
    `lineups`: `rated_lineups` covering these games. Either one missing leaves its columns NaN.
    Returns the feature frame and the league per-60 rates used for shrinkage (so live prediction reuses them)."""
    df = skaters.copy()
    df["assists"] = df["primary_assists"] + df["secondary_assists"]
    df["date"] = _date(df["game_date"])
    df = df.sort_values(["player_id", "date", "game_id"]).reset_index(drop=True)
    df["is_defense"] = (df["position"] == "D").astype(float)
    if shares is not None:
        df = df.merge(shares[["game_id", "player_id"] + SKATER_SHARE_STATS], on=["game_id", "player_id"], how="left")
    else:
        df[SKATER_SHARE_STATS] = np.nan
    if lineups is not None:
        df = df.merge(teammate_quality(df, lineups), on=["game_id", "player_id"], how="left")
    else:
        df[TEAMMATE_COLUMNS] = np.nan

    feats = _prior_features(df, "player_id", SKATER_STATS + list(extra_stats) + SKATER_SHARE_STATS)
    df = pd.concat([df, feats], axis=1)
    df["rest_days"] = _rest_days(df, "player_id")
    df["back_to_back"] = (df["rest_days"] <= 1).astype(float)
    # age at the game date; upcoming rows may lack the birth date, so take it from any of the player's rows
    birth = df.groupby("player_id", sort=False)["birth_date"].transform("first") if "birth_date" in df else pd.NaT
    df["age"] = age_years(df["date"], pd.Series(birth, index=df.index))
    df["age_sq"] = df["age"] ** 2

    # career per-60 rates shrunk toward the position's league rate: stable for veterans, sane for rookies
    by_player = df.groupby("player_id", sort=False)
    # sums over strictly earlier games (optionally decayed by calendar time); unknown upcoming stats count as 0
    day = (df["date"] - EPOCH).dt.days.to_numpy(np.float64)
    prior_sums = _decayed_cumsum(df[["toi"] + SKATER_RATE_STATS], df["player_id"], day, rate_half_life_days,
                                 exclusive=True)
    toi_sum = prior_sums["toi"]
    if league_rates is None:
        league_rates = {}
        for pos, grp in df.groupby("is_defense"):
            hours = grp["toi"].sum() / 3600.0
            league_rates[float(pos)] = {s: float(grp[s].sum() / hours) for s in SKATER_RATE_STATS}
    prior_hours = SHRINK_GAMES * df["is_defense"].map({1.0: 22 * 60, 0.0: 15 * 60}).astype(float) / 3600.0
    for s in SKATER_RATE_STATS:
        stat_sum = prior_sums[s]
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

SKATER_SHARE_COLUMNS = [f"{s}_{w}" for s in SKATER_SHARE_STATS for w in ("l5", "ewm", "season", "career")]

# age at the game date; not in the production feature list: on 2024-25/2025-26 it was within +-0.0004 deviance
# (assists slightly better, hits slightly worse), so props_models keeps it as a variant only
SKATER_AGE_COLUMNS = ["age", "age_sq"]

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
    df["saves"] = df["sog"] - df["goals_against"]
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
