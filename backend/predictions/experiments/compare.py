"""Out-of-time comparison of the original models against baselines and the reworked models.

Train on seasons 2020-2023, early-stop / choose on 2024-25, report on 2025-26 (never touched while choosing).
Reads raw MoneyPuck season files (complete history) and a CSV export of the `games` table, so it runs
without writing to the database. Usage (inside the backend image):
    python -m predictions.experiments.compare --data /scratch --out /scratch/results.json
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, mean_poisson_deviance, mean_absolute_error, roc_auc_score, brier_score_loss
from xgboost import XGBRegressor, XGBClassifier

from predictions import features as F

# rolling-origin folds: (train seasons, early-stopping season, test season)
FOLDS = {"test_2025": ([2020, 2021, 2022, 2023], 2024, 2025),
         "test_2024": ([2020, 2021, 2022], 2023, 2024)}
FOLD = FOLDS["test_2025"]
SEASONS = range(2020, 2027)

# ---------- loading ----------

SKATER_RENAME = {
    "playerId": "player_id", "gameId": "game_id", "playerTeam": "team", "opposingTeam": "opponent",
    "gameDate": "game_date", "I_F_goals": "goals", "I_F_primaryAssists": "primary_assists",
    "I_F_secondaryAssists": "secondary_assists", "I_F_points": "points", "I_F_xGoals": "x_goals",
    "icetime": "toi", "I_F_highDangerShots": "high_danger_shots", "I_F_shotAttempts": "shot_attempts",
    "onIce_xGoalsPercentage": "on_ice_x_goals_percentage", "gameScore": "game_score",
    "I_F_shotsOnGoal": "shots_on_goal",
}
GOALIE_RENAME = {
    "playerId": "player_id", "gameId": "game_id", "playerTeam": "team", "opposingTeam": "opponent",
    "gameDate": "game_date", "icetime": "toi", "xGoals": "x_goals_against", "goals": "goals_against",
    "xOnGoal": "x_sog", "ongoal": "sog", "flurryAdjustedxGoals": "flurry_adjusted_x_goals",
    "highDangerxGoals": "high_danger_x_goals", "highDangerShots": "high_danger_shots",
    "xRebounds": "x_rebounds", "rebounds": "rebounds", "xFreeze": "x_freeze", "freeze": "freeze",
}
TRICODES = {"T.B": "TBL", "S.J": "SJS", "N.J": "NJD", "L.A": "LAK"}

def load_raw(data: Path):
    sk, pp, go = [], [], []
    for s in SEASONS:
        raw = pd.read_pickle(data / f"skaters_{s}.pkl")
        sk.append(raw[raw.situation == "all"])
        pp.append(raw.loc[raw.situation == "5on4", ["playerId", "gameId", "icetime"]])
        g = pd.read_pickle(data / f"goalies_{s}.pkl")
        go.append(g[g.situation == "all"])
    sk = pd.concat(sk).rename(columns=SKATER_RENAME)
    pp = pd.concat(pp).rename(columns={"playerId": "player_id", "gameId": "game_id", "icetime": "pp_toi"})
    sk = sk.merge(pp, on=["player_id", "game_id"], how="left")
    go = pd.concat(go).rename(columns=GOALIE_RENAME)
    for df in (sk, go):
        df[["team", "opponent"]] = df[["team", "opponent"]].replace(TRICODES)
        df["is_home"] = (df["home_or_away"] == "HOME").astype(float)
    games = pd.read_csv(data / "games.csv")
    games["season"] = games["season"] // 10000          # 20252026 -> 2025, matching MoneyPuck
    games = games[games["game_state"].isin(["OFF", "FINAL"])]
    return sk, go, games

def team_offense(sk: pd.DataFrame) -> pd.DataFrame:
    """Team totals summed from skaters (the setup this comparison was run with; 5v5 columns aren't available here)."""
    off = (sk.groupby(["game_id", "team", "opponent", "season", "game_date", "is_home"], as_index=False)
             .agg(gf=("goals", "sum"), xgf=("x_goals", "sum"), saf=("shot_attempts", "sum")))
    against = off[["game_id", "team", "gf", "xgf", "saf"]].rename(columns={"team": "opponent", "gf": "ga", "xgf": "xga", "saf": "saa"})
    off = off.merge(against, on=["game_id", "opponent"], how="left")
    for c in ("xgf5", "xga5", "cf5", "ca5", "gf5", "ga5"):
        off[c] = np.nan
    return off

# ---------- metrics ----------

def count_metrics(y, mu):
    mu = np.clip(mu, 1e-6, None)
    p_any, y_any = 1 - np.exp(-mu), (y >= 1).astype(int)
    return {"poisson_dev": mean_poisson_deviance(y, mu), "mae": mean_absolute_error(y, mu),
            "bias": float(np.mean(mu) - np.mean(y)), **prob_metrics(y_any, p_any, prefix="p1_")}

def prob_metrics(y, p, prefix=""):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return {f"{prefix}logloss": log_loss(y, p, labels=[0, 1]), f"{prefix}auc": roc_auc_score(y, p),
            f"{prefix}brier": brier_score_loss(y, p)}

def calibration(y, p, bins=10):
    q = pd.qcut(p, bins, duplicates="drop")
    return pd.DataFrame({"pred": p, "actual": y}).groupby(q, observed=True).mean().round(4).values.tolist()

def split(df):
    train, valid, test = FOLD
    return (df[df.season.isin(train)], df[df.season == valid], df[df.season == test])

def fit_xgb(cls, params, tr, va, cols, y, margin=None):
    m = cls(**params)
    kw = {}
    if margin:
        kw = {"base_margin": np.log(tr[margin].values), "base_margin_eval_set": [np.log(va[margin].values)]}
    m.fit(tr[cols].astype(np.float32), tr[y], eval_set=[(va[cols].astype(np.float32), va[y])], verbose=False, **kw)
    return m

def predict_count(m, df, cols, margin=None):
    kw = {"base_margin": np.log(df[margin].values)} if margin else {}
    return m.predict(df[cols].astype(np.float32), **kw)

LEGACY_TWEEDIE = dict(objective="reg:tweedie", tweedie_variance_power=1.4, tree_method="hist",
                      eval_metric="tweedie-nloglik@1.4", n_estimators=3000, learning_rate=0.015, max_depth=4,
                      subsample=0.7, colsample_bytree=0.7, colsample_bylevel=0.7, min_child_weight=15,
                      reg_alpha=0.5, reg_lambda=2.0, random_state=42, early_stopping_rounds=75)
LEGACY_CLF = dict(objective="binary:logistic", tree_method="hist", eval_metric="logloss", n_estimators=2000,
                  learning_rate=0.02, max_depth=4, subsample=0.7, colsample_bytree=0.7, colsample_bylevel=0.7,
                  min_child_weight=10, reg_alpha=0.3, reg_lambda=1.5, random_state=42, early_stopping_rounds=75)
POISSON = dict(objective="count:poisson", tree_method="hist", eval_metric="poisson-nloglik", n_estimators=4000,
               learning_rate=0.02, max_depth=4, subsample=0.8, colsample_bytree=0.6, min_child_weight=50,
               reg_lambda=5.0, max_delta_step=0.7, random_state=42, early_stopping_rounds=150)

# ---------- skaters ----------

def run_skaters(sk, team_feats, report):
    df, _ = F.skater_features(sk, team_feats, extra_stats=("pp_toi", "shots_on_goal"))
    for t in ("goals", "assists", "points"):
        df[f"trend_{t}"] = F.league_trend(df, t)
    df = df[df["games_career"] >= 1]   # the original pipeline needs at least one prior game; compare on identical rows
    tr, va, te = split(df)
    pp_cols = [f"pp_toi_{w}" for w in ("l5", "ewm", "season", "career")]
    sog_cols = [f"shots_on_goal_{w}" for w in ("l5", "ewm", "season", "career")]
    new_cols = F.SKATER_FEATURE_COLUMNS
    out = {"rows": {"train": len(tr), "valid": len(va), "test": len(te)}}
    league = {t: tr[t].mean() for t in ("goals", "assists", "points")}
    legacy_reg = {}
    for t in ("goals", "primary_assists", "secondary_assists", "points"):
        legacy_reg[t] = fit_xgb(XGBRegressor, LEGACY_TWEEDIE, tr, va, F.LEGACY_SKATER_FEATURE_COLUMNS, t)
    legacy_pred = {t: m.predict(te[F.LEGACY_SKATER_FEATURE_COLUMNS].astype(np.float32)) for t, m in legacy_reg.items()}
    legacy_pred["assists"] = legacy_pred["primary_assists"] + legacy_pred["secondary_assists"]

    for t in ("goals", "assists", "points"):
        y = te[t].values
        res = {}
        res["baseline_league_mean"] = count_metrics(y, np.full(len(y), league[t]))
        season_or_career = te[f"{t}_season"].where(te["games_season"] >= 5, te[f"{t}_career"]).fillna(league[t]).values
        res["baseline_player_avg"] = count_metrics(y, season_or_career)
        res["baseline_rate_x_toi"] = count_metrics(y, te[f"exp_{t}"].values)
        res["legacy_tweedie"] = count_metrics(y, legacy_pred[t])
        # the original classifiers produced P(>=1) separately
        tr_b, va_b = tr.assign(_y=(tr[t] >= 1).astype(int)), va.assign(_y=(va[t] >= 1).astype(int))
        clf = fit_xgb(XGBClassifier, LEGACY_CLF, tr_b, va_b, F.LEGACY_SKATER_FEATURE_COLUMNS, "_y")
        p_clf = clf.predict_proba(te[F.LEGACY_SKATER_FEATURE_COLUMNS].astype(np.float32))[:, 1]
        res["legacy_tweedie"].update(prob_metrics((y >= 1).astype(int), p_clf, prefix="p1_"))
        res["legacy_tweedie"]["p1_source"] = "separate classifier"
        res["legacy_tweedie"]["inconsistent_pct"] = float(np.mean(p_clf > legacy_pred[t]) * 100)

        variants = {"new_poisson_no_pp": (new_cols, None), "new_poisson": (new_cols + pp_cols + sog_cols, None),
                    "new_poisson_trend": (new_cols + pp_cols + sog_cols, f"trend_{t}")}
        for name, (cols, margin) in variants.items():
            m = fit_xgb(XGBRegressor, POISSON, tr, va, cols, t, margin)
            mu = predict_count(m, te, cols, margin)
            res[name] = count_metrics(y, mu)
            res[name]["trees"] = int(m.best_iteration + 1)
            if name == "new_poisson":
                res[name]["calibration_p1"] = calibration((y >= 1).astype(int), 1 - np.exp(-mu))
                imp = pd.Series(m.get_booster().get_score(importance_type="gain")).sort_values(ascending=False)
                res[name]["top_features"] = imp.head(12).round(2).to_dict()
        out[t] = res
        print(t, {k: round(v["poisson_dev"], 4) for k, v in res.items()}, flush=True)
    report["skaters"] = out

# ---------- goalies ----------

def run_goalies(go, team_feats, report):
    df = F.goalie_features(go, team_feats)
    # only the goalie who played the most in each team-game (the starter, in practice) is what we predict for
    df["is_starter"] = df["toi"] == df.groupby(["game_id", "team"])["toi"].transform("max")
    df = df[df["is_starter"] & (df["games_career"] >= 1)].copy()
    for t in ("goals_against", "sog"):
        df[f"trend_{t}"] = F.league_trend(df, t)
    tr, va, te = split(df)
    out = {"rows": {"train": len(tr), "valid": len(va), "test": len(te)}}
    for t in ("goals_against", "sog"):
        y = te[t].values
        res = {"baseline_league_mean": count_metrics(y, np.full(len(y), tr[t].mean()))}
        res["baseline_goalie_avg"] = count_metrics(
            y, te[f"{t}_season"].where(te["games_season"] >= 5, te[f"{t}_career"]).fillna(tr[t].mean()).values)
        legacy = fit_xgb(XGBRegressor, LEGACY_TWEEDIE, tr, va, F.LEGACY_GOALIE_FEATURE_COLUMNS, t)
        res["legacy_tweedie"] = count_metrics(y, legacy.predict(te[F.LEGACY_GOALIE_FEATURE_COLUMNS].astype(np.float32)))
        for name, margin in (("new_poisson", None), ("new_poisson_trend", f"trend_{t}")):
            m = fit_xgb(XGBRegressor, POISSON | {"min_child_weight": 20}, tr, va, F.GOALIE_FEATURE_COLUMNS, t, margin)
            res[name] = count_metrics(y, predict_count(m, te, F.GOALIE_FEATURE_COLUMNS, margin))
            res[name]["trees"] = int(m.best_iteration + 1)
        imp = pd.Series(m.get_booster().get_score(importance_type="gain")).sort_values(ascending=False)
        res["new_poisson"]["top_features"] = imp.head(10).round(2).to_dict()
        out[t] = res
        print(t, {k: round(v["poisson_dev"], 4) for k, v in res.items()}, flush=True)
    report["goalies"] = out

# ---------- teams ----------

def legacy_team_frame(sk, go, games):
    """Rebuilds the original team pipeline: 5-game in-season rolling means of 14 stats, starting-goalie goals
    against, home rows only, label = skater goals > starting goalie goals against (no shootouts / pulled goalies)."""
    off = (sk.groupby(["game_id", "team", "season", "game_date", "is_home"], as_index=False)
             .agg(goals=("goals", "sum"), x_goals=("x_goals", "sum"), shot_attempts=("shot_attempts", "sum"),
                  high_danger_shots=("high_danger_shots", "sum"), points=("points", "sum"),
                  primary_assists=("primary_assists", "sum"), avg_on_ice_x_goals_percentage=("on_ice_x_goals_percentage", "mean"),
                  avg_game_score=("game_score", "mean")))
    starters = go.loc[go["toi"] == go.groupby(["game_id", "team"])["toi"].transform("max")]
    starters = starters.drop_duplicates(["game_id", "team"]).rename(columns={
        "sog": "sog_against", "high_danger_shots": "high_danger_shots_against",
        "high_danger_x_goals": "high_danger_x_goals_against", "flurry_adjusted_x_goals": "flurry_adjusted_x_goals_against"})
    d = off.merge(starters[["game_id", "team", "goals_against", "x_goals_against", "sog_against", "high_danger_shots_against",
                            "high_danger_x_goals_against", "flurry_adjusted_x_goals_against"]], on=["game_id", "team"])
    stats = ["goals", "x_goals", "shot_attempts", "high_danger_shots", "points", "primary_assists",
             "avg_on_ice_x_goals_percentage", "avg_game_score", "goals_against", "x_goals_against", "sog_against",
             "high_danger_shots_against", "high_danger_x_goals_against", "flurry_adjusted_x_goals_against"]
    d = d.sort_values(["team", "game_date", "game_id"])
    roll = d.groupby(["team", "season"])[stats].transform(lambda s: s.rolling(5, min_periods=5).mean().shift(1))
    cols = [f"r_{s}" for s in stats]
    d[cols] = roll.values
    home, away = d[d.is_home == 1], d[d.is_home == 0]
    m = home.merge(away[["game_id"] + cols].rename(columns={c: "opp_" + c for c in cols}), on="game_id")
    m = m.dropna(subset=cols + ["opp_" + c for c in cols])
    m["legacy_label"] = (m["goals"] > m["goals_against"]).astype(int)
    m = m.merge(games[["id", "home_score", "away_score"]].rename(columns={"id": "game_id"}), on="game_id")
    m["true_label"] = (m["home_score"] > m["away_score"]).astype(int)
    return m, cols + ["opp_" + c for c in cols]

def run_teams(sk, go, games, team_feats, report):
    out = {}
    leg, leg_cols = legacy_team_frame(sk, go, games)
    out["legacy_label_wrong_pct"] = float((leg["legacy_label"] != leg["true_label"]).mean() * 100)
    ltr, lva, lte = split(leg)

    frame = F.build_team_model_frame(games, team_feats)
    frame = frame[(frame["game_id"] // 10000 % 100 == 2) & frame["home_win"].notna()]   # regular season, completed
    frame = frame[frame["home_games_season"].notna()]
    tr, va, te = split(frame)
    # score every model on the same test games (the legacy model needs 5 prior games for both teams)
    te = te[te["game_id"].isin(lte["game_id"])]
    y = te["home_win"].astype(int).values
    out["rows"] = {"train": len(tr), "valid": len(va), "test": len(te)}
    res = {"baseline_home_rate": prob_metrics(y, np.full(len(y), tr["home_win"].mean())),
           "baseline_elo": prob_metrics(y, te["elo_prob"].values)}
    lte = lte.set_index("game_id").loc[te["game_id"]].reset_index()
    legacy_params = dict(LEGACY_CLF, learning_rate=0.04)
    leg_model = fit_xgb(XGBClassifier, legacy_params, ltr, lva, leg_cols, "legacy_label")
    res["legacy_xgb"] = prob_metrics(y, leg_model.predict_proba(lte[leg_cols].astype(np.float32))[:, 1])

    small = ["elo_diff", "diff_xg_pct_ewm", "diff_xg_pct_season", "diff_g_pct_ewm", "diff_gsax_ewm", "diff_rest_days",
             "home_rest_days", "away_rest_days"]
    lr_tr = tr.dropna(subset=small)
    mu, sd = lr_tr[small].mean(), lr_tr[small].std()
    lr = LogisticRegression(C=1.0, max_iter=1000).fit(((lr_tr[small] - mu) / sd), lr_tr["home_win"].astype(int))
    p_lr = lr.predict_proba(((te[small] - mu) / sd).fillna(0))[:, 1]
    res["new_logistic"] = prob_metrics(y, p_lr)
    res["new_logistic"]["coefs"] = dict(zip(small, np.round(lr.coef_[0], 3)))
    res["new_logistic"]["calibration"] = calibration(y, p_lr, bins=5)

    clf_params = dict(objective="binary:logistic", tree_method="hist", eval_metric="logloss", n_estimators=3000,
                      learning_rate=0.01, max_depth=2, subsample=0.8, colsample_bytree=0.6, min_child_weight=30,
                      reg_lambda=5.0, random_state=42, early_stopping_rounds=200)
    m = fit_xgb(XGBClassifier, clf_params, tr.assign(y=tr.home_win.astype(int)), va.assign(y=va.home_win.astype(int)),
                F.TEAM_FEATURE_COLUMNS, "y")
    p_x = m.predict_proba(te[F.TEAM_FEATURE_COLUMNS].astype(np.float32))[:, 1]
    res["new_xgb"] = prob_metrics(y, p_x)
    res["new_xgb"]["trees"] = int(m.best_iteration + 1)
    res["new_blend"] = prob_metrics(y, (p_x + p_lr) / 2)
    for r in res.values():
        r["accuracy"] = None
    for name, p in {"baseline_elo": te["elo_prob"].values, "new_logistic": p_lr, "new_xgb": p_x,
                    "legacy_xgb": leg_model.predict_proba(lte[leg_cols].astype(np.float32))[:, 1],
                    "baseline_home_rate": np.full(len(y), tr["home_win"].mean())}.items():
        res[name]["accuracy"] = float(np.mean((p > 0.5) == y))
    out["win"] = res
    print({k: (round(v["logloss"], 4), round(v["auc"], 4)) for k, v in res.items()}, flush=True)
    report["teams"] = out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/scratch")
    ap.add_argument("--out", default="/scratch/results.json")
    ap.add_argument("--only", default="skaters,goalies,teams")
    ap.add_argument("--fold", default="test_2025", choices=list(FOLDS))
    args = ap.parse_args()
    global FOLD
    FOLD = FOLDS[args.fold]
    t0 = time.time()
    sk, go, games = load_raw(Path(args.data))
    team_games = F.build_team_games(team_offense(sk))
    team_feats = F.team_history_features(team_games)
    print(f"loaded + team features in {time.time() - t0:.0f}s", flush=True)
    report = {}
    only = args.only.split(",")
    if "teams" in only:
        run_teams(sk, go, games, team_feats, report)
    if "goalies" in only:
        run_goalies(go, team_feats, report)
    if "skaters" in only:
        run_skaters(sk, team_feats, report)
    Path(args.out).write_text(json.dumps(report, indent=1, default=float))
    print(f"done in {time.time() - t0:.0f}s")

if __name__ == "__main__":
    main()
