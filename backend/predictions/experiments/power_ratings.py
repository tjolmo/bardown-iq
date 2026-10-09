"""Opponent-adjusted, time-decayed team power ratings.

    python -m predictions.experiments.power_ratings [--tune] [--out /scratch/feat_power.pkl]

`kalman_ratings` runs one joint Kalman filter over every franchise: each team has an offense rating `o` and a defense
rating `d` (both "per game, versus league average", higher is better), plus a league mean `m` and a half home edge `h`:

    home_for  = m + h + o_home - d_away + noise
    away_for  = m - h + o_away - d_home + noise

Ratings drift as a random walk (variance `q_day` per day elapsed) and at each new season are shrunk toward 0 by `carry`
and get `offseason_var` extra variance. Every game on a date is rated from the state *before* that date's results.
Games without stats (upcoming, or missing data) are rated but don't update. Playoff games update the ratings too.

`decayed_ridge_ratings` is the Massey-style alternative: the same design, solved as a ridge regression over all prior
games with exponentially decaying weights (kept as running normal equations, so it's one 70x70 solve per date).
"""
import argparse
import asyncio
import time
import numpy as np
import pandas as pd

# stat name -> (for columns, against columns, observation noise variance of one team-game, roughly the raw variance).
# Several columns are averaged: "gx" is the mean of actual goals and all-situation xG.
STATS = {"xg5": (("xgf5",), ("xga5",), 0.40), "xg": (("xgf",), ("xga",), 0.95), "g": (("gf",), ("ga",), 2.85),
         "gx": (("gf", "xgf"), ("ga", "xga"), 1.6)}

# tuned on test seasons 2015-2021 only (tune_score); q_day, offseason_var in (stat per game)^2, carry = share kept
# across the offseason. Extra offseason variance never helped: shrinking toward average (carry) does that job.
KALMAN_PARAMS = {
    "xg5": dict(q_day=2e-5, offseason_var=0.0, carry=0.9),
    "xg": dict(q_day=5e-5, offseason_var=0.0, carry=0.9),
    "g": dict(q_day=1.5e-4, offseason_var=0.0, carry=0.9),
    "gx": dict(q_day=1e-4, offseason_var=0.0, carry=0.9),
}
RIDGE_PARAMS = {"xg5": dict(half_life_days=60.0, alpha=20.0)}

# franchises the NHL / the DB keep separate that should share one rating history
FRANCHISE_ALIASES = {"ATL": "WPG", "PHX": "ARI", "UTA": "ARI"}


def franchise_of(tri: str, franchise_ids: dict[str, int] | None = None) -> str:
    """Rating key for a tri code. `franchise_ids` (teams.tri_code -> franchise_id) merges any codes sharing an id;
    FRANCHISE_ALIASES covers relocations the DB treats as a new franchise (ARI -> UTA)."""
    tri = FRANCHISE_ALIASES.get(tri, tri)
    if franchise_ids and tri in franchise_ids:
        same = sorted(t for t, f in franchise_ids.items() if f == franchise_ids[tri])
        return FRANCHISE_ALIASES.get(same[0], same[0])
    return tri


def _schedule(team_stats: pd.DataFrame, games: pd.DataFrame | None, for_cols, against_cols) -> pd.DataFrame:
    """One row per game: id, season, date, home, away, y_home (home `for`), y_away (home `against`) — NaN if unplayed."""
    home = team_stats[team_stats["is_home"] == 1]
    sched = pd.DataFrame({"id": home["game_id"].values, "season": home["season"].values, "date": home["game_date"].values,
                          "home": home["team"].values, "away": home["opponent"].values,
                          "y_home": home[list(for_cols)].mean(axis=1, skipna=False).values,
                          "y_away": home[list(against_cols)].mean(axis=1, skipna=False).values})
    if games is not None and len(games):
        extra = games[~games["id"].isin(sched["id"])]
        sched = pd.concat([sched, pd.DataFrame({
            "id": extra["id"].values, "season": extra["season"].values, "date": extra["date"].values,
            "home": extra["home_team_tri_code"].values, "away": extra["away_team_tri_code"].values,
            "y_home": np.nan, "y_away": np.nan})], ignore_index=True)
    return sched.sort_values(["date", "id"]).reset_index(drop=True)


def _setup(sched, franchise_ids):
    keys = sorted({franchise_of(t, franchise_ids) for t in pd.concat([sched["home"], sched["away"]]).unique()})
    idx = {k: i for i, k in enumerate(keys)}
    hi = np.array([idx[franchise_of(t, franchise_ids)] for t in sched["home"]])
    ai = np.array([idx[franchise_of(t, franchise_ids)] for t in sched["away"]])
    dates = pd.to_datetime(sched["date"].astype(str), format="%Y%m%d").to_numpy().astype("datetime64[D]").astype(np.int64)
    return len(keys), hi, ai, dates


def _output(sched, pre_o, pre_d, pre_sd, prefix):
    """Long frame (game_id, team) of pre-game ratings, home and away rows."""
    n = len(sched)
    rows = []
    for side, k in (("home", 0), ("away", 1)):
        rows.append(pd.DataFrame({"game_id": sched["id"].values, "team": sched[side].values,
                                  f"{prefix}_off": pre_o[:, k], f"{prefix}_def": pre_d[:, k],
                                  f"{prefix}_rating": pre_o[:, k] + pre_d[:, k], f"{prefix}_sd": pre_sd[:, k]}))
    return pd.concat(rows, ignore_index=True)


def kalman_ratings(team_stats: pd.DataFrame, games: pd.DataFrame | None = None, stat: str = "xg5",
                   franchise_ids: dict[str, int] | None = None, q_day: float | None = None,
                   offseason_var: float | None = None, carry: float | None = None, obs_var: float | None = None,
                   prior_var: float = 0.05, prefix: str | None = None) -> pd.DataFrame:
    """Pre-game opponent-adjusted ratings for every game in `team_stats` (load_team_stats columns) and `games`
    (load_games columns, optional, for unplayed games). Returns one row per (game_id, team) with
    <prefix>_off, _def, _rating (= off + def, expected per-game `stat` differential vs an average team) and _sd."""
    for_cols, against_cols, default_r = STATS[stat]
    p = KALMAN_PARAMS.get(stat, KALMAN_PARAMS["xg5"])
    q_day = p["q_day"] if q_day is None else q_day
    offseason_var = p["offseason_var"] if offseason_var is None else offseason_var
    carry = p["carry"] if carry is None else carry
    r = default_r if obs_var is None else obs_var
    prefix = prefix or f"pr_{stat}"

    sched = _schedule(team_stats, games, for_cols, against_cols)
    N, hi, ai, days = _setup(sched, franchise_ids)
    n = 2 * N + 2
    M, Hh = 2 * N, 2 * N + 1
    x = np.zeros(n)
    P = np.eye(n) * prior_var
    P[M, M], P[Hh, Hh] = 10.0, 1.0
    R = np.eye(2) * r
    team_diag = np.arange(2 * N)
    seasons, y_h, y_a = sched["season"].to_numpy(), sched["y_home"].to_numpy(), sched["y_away"].to_numpy()

    G = len(sched)
    pre_o, pre_d, pre_sd = np.empty((G, 2)), np.empty((G, 2)), np.empty((G, 2))
    starts = np.flatnonzero(np.r_[True, days[1:] != days[:-1]])
    ends = np.r_[starts[1:], G]
    last_day, last_season = days[0], seasons[0]
    for s, e in zip(starts, ends):
        # time update
        if seasons[s] != last_season:
            x[:2 * N] *= carry
            P[:2 * N, :] *= carry
            P[:, :2 * N] *= carry
            P[team_diag, team_diag] += offseason_var
            last_season = seasons[s]
        dt = days[s] - last_day
        P[team_diag, team_diag] += q_day * dt
        P[M, M] += 1e-6 * dt
        P[Hh, Hh] += 1e-7 * dt
        last_day = days[s]
        # pre-game snapshot for the whole date
        for side, ix in ((0, hi[s:e]), (1, ai[s:e])):
            pre_o[s:e, side] = x[ix]
            pre_d[s:e, side] = x[N + ix]
            pre_sd[s:e, side] = np.sqrt(P[ix, ix] + P[N + ix, N + ix] + 2 * P[ix, N + ix])
        # measurement updates
        for g in range(s, e):
            if np.isnan(y_h[g]) or np.isnan(y_a[g]):
                continue
            h, a = hi[g], ai[g]
            H = np.zeros((2, n))
            H[0, M] = H[1, M] = 1.0
            H[0, Hh], H[1, Hh] = 1.0, -1.0
            H[0, h], H[0, N + a] = 1.0, -1.0
            H[1, a], H[1, N + h] = 1.0, -1.0
            PHt = P @ H.T
            S = H @ PHt + R
            K = PHt @ np.linalg.inv(S)
            x += K @ (np.array([y_h[g], y_a[g]]) - H @ x)
            P -= K @ PHt.T
        P = (P + P.T) / 2
    return _output(sched, pre_o, pre_d, pre_sd, prefix)


def decayed_ridge_ratings(team_stats: pd.DataFrame, games: pd.DataFrame | None = None, stat: str = "xg5",
                          franchise_ids: dict[str, int] | None = None, half_life_days: float | None = None,
                          alpha: float | None = None, prefix: str | None = None) -> pd.DataFrame:
    """Massey-style ridge on the same design (offense/defense per team, league mean, home edge) refit every date on
    all earlier games with weight 0.5 ** (age_days / half_life_days). Summer gaps decay old seasons naturally."""
    for_cols, against_cols, _ = STATS[stat]
    p = RIDGE_PARAMS.get(stat, RIDGE_PARAMS["xg5"])
    half_life_days = p["half_life_days"] if half_life_days is None else half_life_days
    alpha = p["alpha"] if alpha is None else alpha
    prefix = prefix or f"prr_{stat}"
    sched = _schedule(team_stats, games, for_cols, against_cols)
    N, hi, ai, days = _setup(sched, franchise_ids)
    n = 2 * N + 2
    M, Hh = 2 * N, 2 * N + 1
    A, b = np.zeros((n, n)), np.zeros(n)
    pen = np.full(n, alpha)
    pen[M] = pen[Hh] = 1e-6
    y_h, y_a = sched["y_home"].to_numpy(), sched["y_away"].to_numpy()
    G = len(sched)
    pre_o, pre_d, pre_sd = np.empty((G, 2)), np.empty((G, 2)), np.full((G, 2), np.nan)
    starts = np.flatnonzero(np.r_[True, days[1:] != days[:-1]])
    ends = np.r_[starts[1:], G]
    last_day = days[0]
    x = np.zeros(n)
    for s, e in zip(starts, ends):
        decay = 0.5 ** ((days[s] - last_day) / half_life_days)
        A *= decay
        b *= decay
        last_day = days[s]
        if A[M, M] > 0:
            x = np.linalg.solve(A + np.diag(pen), b)
        for side, ix in ((0, hi[s:e]), (1, ai[s:e])):
            pre_o[s:e, side] = x[ix]
            pre_d[s:e, side] = x[N + ix]
        for g in range(s, e):
            if np.isnan(y_h[g]) or np.isnan(y_a[g]):
                continue
            h, a = hi[g], ai[g]
            r1 = np.zeros(n); r1[[M, Hh, h, N + a]] = (1, 1, 1, -1)
            r2 = np.zeros(n); r2[[M, Hh, a, N + h]] = (1, -1, 1, -1)
            A += np.outer(r1, r1) + np.outer(r2, r2)
            b += r1 * y_h[g] + r2 * y_a[g]
    return _output(sched, pre_o, pre_d, pre_sd, prefix)


def game_features(long: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Long (game_id, team) ratings -> one row per game with home_/away_/diff_ columns. `games` needs id and
    home/away tri codes."""
    cols = [c for c in long.columns if c not in ("game_id", "team")]
    g = games[["id", "home_team_tri_code", "away_team_tri_code"]].rename(columns={"id": "game_id"})
    out = g.merge(long.rename(columns={"team": "home_team_tri_code", **{c: f"home_{c}" for c in cols}}),
                  on=["game_id", "home_team_tri_code"], how="left")
    out = out.merge(long.rename(columns={"team": "away_team_tri_code", **{c: f"away_{c}" for c in cols}}),
                    on=["game_id", "away_team_tri_code"], how="left")
    for c in cols:
        if not c.endswith("_sd"):
            out[f"diff_{c}"] = out[f"home_{c}"] - out[f"away_{c}"]
    return out.drop(columns=["home_team_tri_code", "away_team_tri_code"])


# ---------------- experiment driver ----------------

async def _load():
    from sqlalchemy import text
    from app.database import AsyncSessionLocal
    from predictions.data import load_team_stats, load_games
    async with AsyncSessionLocal() as db:
        fr = (await db.execute(text("select tri_code, franchise_id from teams"))).all()
        return await load_team_stats(db), await load_games(db), {t: f for t, f in fr}


def _summ(r):
    return {**{k: round(v["model"], 4) for k, v in r.items() if isinstance(v, dict)},
            "mean": round(r["mean_model"], 4), "mkt": round(r["mean_market"], 4)}


# production TEAM_FEATURE_COLUMNS as of the 0.6650 baseline (features.py is being edited concurrently)
BASE_COLS = ["elo_diff", "diff_xg_pct_ewm", "diff_xg_pct_season", "diff_g_pct_ewm", "diff_gsax_ewm",
             "diff_rest_days", "home_rest_days", "away_rest_days", "diff_xg5_pct_season", "diff_xg5_pct_ewm",
             "diff_starter_gsax60"]

TUNE_SEASONS = [2015, 2016, 2017, 2018, 2019, 2020, 2021]


def tune_score(frame, cols, seasons=TUNE_SEASONS) -> float:
    """frames.evaluate's rolling-origin log loss, without the market (no lines before 2019)."""
    from sklearn.metrics import log_loss
    from predictions.train import _team_logistic
    out = []
    for test in seasons:
        tr, te = frame[frame["season"] < test - 1], frame[frame["season"] == test]
        p = _team_logistic().fit(tr[cols], tr["home_win"].astype(int)).predict_proba(te[cols])[:, 1]
        out.append(log_loss(te["home_win"], p))
    return float(np.mean(out))


def tune(team_stats, games, fr, frame, base):
    from predictions.experiments.frames import evaluate
    games_ = games[["id", "home_team_tri_code", "away_team_tri_code"]]
    results = []
    for stat in ("xg5", "xg", "g"):
        for q in (5e-6, 2e-5, 5e-5, 1.5e-4):
            for off in (0.0, 0.005, 0.015, 0.04):
                for carry in (0.4, 0.6, 0.8):
                    long = kalman_ratings(team_stats, games, stat, fr, q_day=q, offseason_var=off, carry=carry,
                                          prefix="t")
                    f = frame.merge(game_features(long, games_), on="game_id", how="left")
                    alone = tune_score(f, ["diff_t_rating"])
                    plus = tune_score(f, base + ["diff_t_rating"])
                    results.append((stat, q, off, carry, alone, plus))
                    print("kalman", stat, q, off, carry, round(alone, 5), round(plus, 5), flush=True)
    for hl in (20, 40, 60, 100, 150):
        for alpha in (5, 20, 60):
            long = decayed_ridge_ratings(team_stats, games, "xg5", fr, half_life_days=hl, alpha=alpha, prefix="t")
            f = frame.merge(game_features(long, games_), on="game_id", how="left")
            alone = tune_score(f, ["diff_t_rating"])
            plus = tune_score(f, base + ["diff_t_rating"])
            print("ridge", hl, alpha, round(alone, 5), round(plus, 5), flush=True)
    return results


if __name__ == "__main__":
    from predictions import features as F
    from predictions.experiments.frames import evaluate
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", default="/scratch/team_frame.pkl")
    ap.add_argument("--out", default="/scratch/feat_power.pkl")
    ap.add_argument("--tune", action="store_true")
    args = ap.parse_args()
    team_stats, games, fr = asyncio.run(_load())
    frame = pd.read_pickle(args.frame)
    base = list(F.TEAM_FEATURE_COLUMNS)  # current production list (includes roster ratings)
    if args.tune:
        tune(team_stats, games, fr, frame, base)
        raise SystemExit
    games_ = games[["id", "home_team_tri_code", "away_team_tri_code"]]
    feats, timings = None, {}
    for stat in ("xg5", "xg", "g", "gx"):
        t0 = time.time()
        long = kalman_ratings(team_stats, games, stat, fr)
        timings[stat] = round(time.time() - t0, 2)
        gf = game_features(long, games_)
        feats = gf if feats is None else feats.merge(gf, on="game_id")
    t0 = time.time()
    gf = game_features(decayed_ridge_ratings(team_stats, games, "xg5", fr), games_)
    timings["ridge_xg5"] = round(time.time() - t0, 2)
    feats = feats.merge(gf, on="game_id")
    def _pr_name(c):  # home_pr_xg5_rating -> pr_home_xg5_rating, home_prr_xg5_off -> pr_home_ridge_xg5_off
        if c == "game_id":
            return c
        side, rest = c.split("_", 1)
        return "pr_" + side + "_" + (rest.replace("prr_", "ridge_", 1) if rest.startswith("prr_") else rest[3:])
    feats.rename(columns=_pr_name).to_pickle(args.out)
    print("runtime (s):", timings, "| rows:", len(feats), "| cols:", list(feats.columns))
    f = frame.merge(feats, on="game_id", how="left")
    print("missing pr in frame:", int(f["diff_pr_xg5_rating"].isna().sum()))
    no_elo = [c for c in base if c != "elo_diff"]
    R = lambda *st: [f"diff_pr_{x}_rating" for x in st]
    runs = {
        "baseline (current prod)": base,
        "old baseline (11 cols)": BASE_COLS,
        "elo alone": ["elo_diff"],
        **{f"pr_{x} alone": R(x) for x in ("xg5", "xg", "g", "gx")},
        "ridge xg5 alone": ["diff_prr_xg5_rating"],
        **{f"base + pr_{x}": base + R(x) for x in ("xg5", "g", "gx")},
        "base + pr_xg5 off/def": base + ["diff_pr_xg5_off", "diff_pr_xg5_def"],
        "base + pr_g,xg5": base + R("g", "xg5"),
        **{f"base - elo + pr_{x}": no_elo + R(x) for x in ("xg5", "g", "gx")},
        "base - elo + pr_g,xg5": no_elo + R("g", "xg5"),
        "old base + pr_g": BASE_COLS + R("g"),
        "old base - elo + pr_g": [c for c in BASE_COLS if c != "elo_diff"] + R("g"),
    }
    for name, cols in runs.items():
        print(f"{name:28s}", _summ(evaluate(f, cols)), "| pre-2022:",
              round(tune_score(f, cols), 4), flush=True)
