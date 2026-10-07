"""Score models vs the binary win model, and standings context.

    python -m predictions.experiments.score_models --frame /scratch/e_frame_po.pkl --outcomes /scratch/e_nhlapi/outcomes.csv

Win models compared on the frames.py protocol (train on seasons before test-1, playoffs in training):
  - binary logistic on TEAM_FEATURE_COLUMNS (production)
  - three-class multinomial logistic (regulation home / OT-SO / regulation away), P(home) = P(reg home) + s P(OT)
  - two Poisson GLMs for regulation goals, independent with tie inflation, OT/SO split s
Selection seasons 2016-21, confirmation 2022-25, playoffs 2019-25, and the March-April regular-season subset.
"""
import argparse
import asyncio
import json
import numpy as np
import pandas as pd
from scipy.stats import poisson
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, PoissonRegressor
from sklearn.metrics import log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from predictions import features as F
from predictions.train import _team_logistic

SELECT, CONFIRM, PLAYOFFS = list(range(2016, 2022)), [2022, 2023, 2024, 2025], list(range(2019, 2026))
MAX_GOALS = 15

async def _load_db():
    from app.database import AsyncSessionLocal
    from predictions.data import load_team_stats, load_games
    async with AsyncSessionLocal() as db:
        return await load_team_stats(db), await load_games(db)

def side_strength(team_stats: pd.DataFrame) -> pd.DataFrame:
    """Offence / defence rates per side (the win frame only keeps shares)."""
    tf = F.team_history_features(F.build_team_games(team_stats))
    cols = ["team_xgf_ewm", "team_xga_ewm", "team_gf_ewm", "team_ga_ewm", "team_xgf_season", "team_xga_season",
            "team_xgf5_ewm", "team_xga5_ewm"]
    return tf[["game_id", "team"] + cols]

def add_sides(frame: pd.DataFrame, side: pd.DataFrame) -> pd.DataFrame:
    for prefix, col in (("home_", "home_team_tri_code"), ("away_", "away_team_tri_code")):
        r = side.rename(columns={c: prefix + c.removeprefix("team_") for c in side.columns if c not in ("game_id", "team")})
        frame = frame.merge(r.rename(columns={"team": col}), on=["game_id", col], how="left")
    return frame

GOAL_SIDE = ["xgf_ewm", "xga_ewm", "gf_ewm", "ga_ewm", "xgf_season", "xga_season", "xgf5_ewm", "xga5_ewm"]
GOAL_COLUMNS = F.TEAM_FEATURE_COLUMNS + [f"{s}_{c}" for s in ("home", "away") for c in GOAL_SIDE]

# ---------- models: each returns P(home win) for test rows ----------

def binary(tr, te, cols):
    return _team_logistic().fit(tr[cols], tr["home_win"].astype(int)).predict_proba(te[cols])[:, 1]

def three_class(tr, te, cols, C=1.0):
    m = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(max_iter=2000, C=C))
    m.fit(tr[cols], tr["result3"].astype(int))
    p = m.predict_proba(te[cols])           # classes 0 reg away, 1 OT/SO, 2 reg home
    ot = tr["result3"] == 1
    s = (tr.loc[ot, "home_win"]).mean()
    return p[:, 2] + s * p[:, 1], p

def poisson_win_prob(lh, la, tie_inflation=1.0, ot_home_share=0.5):
    """P(home win incl. OT/SO), P(regulation tie), from independent Poisson regulation goals with the diagonal
    scaled by `tie_inflation` (and the off-diagonal renormalised)."""
    g = np.arange(MAX_GOALS + 1)
    ph, pa = poisson.pmf(g[None, :], np.asarray(lh)[:, None]), poisson.pmf(g[None, :], np.asarray(la)[:, None])
    joint = ph[:, :, None] * pa[:, None, :]
    win = joint[:, np.tril_indices(MAX_GOALS + 1, -1)[0], np.tril_indices(MAX_GOALS + 1, -1)[1]].sum(1)
    tie = np.einsum("nii->n", joint)
    lose = joint.sum((1, 2)) - win - tie
    tie2 = np.clip(tie * tie_inflation, 0, 1)
    scale = (1 - tie2) / (win + lose)
    return win * scale + ot_home_share * tie2, tie2, win * scale, lose * scale

def poisson_models(tr, te, cols, alpha=1e-3):
    mk = lambda: make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), PoissonRegressor(alpha=alpha, max_iter=1000))
    mh, ma = mk().fit(tr[cols], tr["reg_home"]), mk().fit(tr[cols], tr["reg_away"])
    lh_tr, la_tr = mh.predict(tr[cols]), ma.predict(tr[cols])
    _, tie_tr, _, _ = poisson_win_prob(lh_tr, la_tr)
    infl = (tr["result3"] == 1).mean() / tie_tr.mean()
    s = tr.loc[tr["result3"] == 1, "home_win"].mean()
    lh, la = mh.predict(te[cols]), ma.predict(te[cols])
    p, tie, _, _ = poisson_win_prob(lh, la, infl, s)
    return p, {"lh": lh, "la": la, "tie": tie, "infl": infl, "s": s}

# ---------- evaluation ----------

def rolling(frame, fn, seasons, playoffs=False, months=None):
    """Mean log loss over test seasons, plus market log loss on the same games where priced."""
    res = []
    for test in seasons:
        tr = frame[frame["season"] < test - 1]
        te = frame[(frame["season"] == test) & ((frame["is_playoff"] == 1) == playoffs)]
        if months is not None:
            te = te[(te["date"] // 100 % 100).isin(months)]
        out = fn(tr, te)
        p = out[0] if isinstance(out, tuple) else out
        y = te["home_win"].astype(int)
        m = te["mkt"].notna().to_numpy()
        res.append((log_loss(y, p, labels=[0, 1]), log_loss(y[m], te["mkt"][m], labels=[0, 1]) if m.sum() > 20 else np.nan,
                    len(te)))
    r = np.array(res)
    return {"model": round(float(r[:, 0].mean()), 4), "market": round(float(np.nanmean(r[:, 1])), 4) if not np.isnan(r[:, 1]).all() else None,
            "per_season": [round(x, 4) for x in r[:, 0]]}

def suite(frame, fn):
    return {"select_2016_21": rolling(frame, fn, SELECT), "confirm_2022_25": rolling(frame, fn, CONFIRM),
            "playoffs_2019_25": rolling(frame, fn, PLAYOFFS, playoffs=True),
            "mar_apr_select": rolling(frame, fn, SELECT, months=[3, 4]),
            "mar_apr_confirm": rolling(frame, fn, CONFIRM, months=[3, 4])}

def label(frame: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    o = outcomes[["game_id", "last_period_type"]]
    f = frame.merge(o, on="game_id", how="left")
    f["went_ot"] = f["last_period_type"].isin(["OT", "SO"])
    hw = f["home_score"] > f["away_score"]
    f["result3"] = np.where(f["went_ot"], 1, np.where(hw, 2, 0))
    # regulation goals: an OT/SO game was tied after 60 minutes at the loser's final score
    low = np.minimum(f["home_score"], f["away_score"])
    f["reg_home"] = np.where(f["went_ot"], low, f["home_score"])
    f["reg_away"] = np.where(f["went_ot"], low, f["away_score"])
    return f

def totals(frame, seasons):
    """Poisson model total vs the market total line: mean difference and P(over) log loss on non-push games."""
    rows = []
    for test in seasons:
        tr, te = frame[frame["season"] < test - 1], frame[(frame["season"] == test) & (frame["is_playoff"] == 0)]
        _, info = poisson_models(tr, te, GOAL_COLUMNS)
        te = te.assign(lh=info["lh"], la=info["la"], tie=info["tie"])
        rows.append(te)
    t = pd.concat(rows)
    t = t[t["total_line"].notna()]
    exp_total = t["lh"] + t["la"] + t["tie"]   # the OT/SO winner counts as a goal for totals
    actual = t["home_score"] + t["away_score"]
    # P(over): regulation total distribution (convolution of two Poissons ~ Poisson(lh+la), with the tie mass
    # adding one goal); approximate with Poisson(lh+la) and shift tie games by +1 via mixture
    lam = (t["lh"] + t["la"]).to_numpy()
    line = t["total_line"].to_numpy()
    # P(final total > line) where final = reg + 1{tie}; tie only when reg total is even, approximate the +1 as mixture
    p_over = (1 - t["tie"]) * (1 - poisson.cdf(np.floor(line), lam)) + t["tie"] * (1 - poisson.cdf(np.floor(line) - 1, lam))
    push = actual == line
    y = (actual > line)[~push].astype(int)
    pv = np.clip(p_over[~push], 1e-4, 1 - 1e-4)
    return {"games": int(len(t)), "mean_model_total": round(float(exp_total.mean()), 3), "mean_line": round(float(line.mean()), 3),
            "mean_actual": round(float(actual.mean()), 3),
            "corr_model_total_vs_line": round(float(np.corrcoef(exp_total, line)[0, 1]), 3),
            "mae_model_vs_actual": round(float((exp_total - actual).abs().mean()), 3),
            "mae_line_vs_actual": round(float((line - actual).abs().mean()), 3),
            "over_rate": round(float(y.mean()), 4), "mean_p_over": round(float(pv.mean()), 4),
            "p_over_logloss": round(float(log_loss(y, pv)), 4), "const_rate_logloss": round(float(log_loss(y, np.full(len(y), y.mean()))), 4)}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", default="/scratch/e_frame_po.pkl")
    ap.add_argument("--outcomes", default="/scratch/e_nhlapi/outcomes.csv")
    ap.add_argument("--out", default="/scratch/e_score_models.json")
    args = ap.parse_args()
    team_stats, games = asyncio.run(_load_db())
    frame = label(add_sides(pd.read_pickle(args.frame), side_strength(team_stats)), pd.read_csv(args.outcomes))
    frame = frame[frame["last_period_type"].notna()].reset_index(drop=True)
    print(len(frame), "games; OT/SO rate", round(frame["went_ot"].mean(), 4))
    cols = F.TEAM_FEATURE_COLUMNS
    res = {
        "binary": suite(frame, lambda tr, te: binary(tr, te, cols)),
        "three_class": suite(frame, lambda tr, te: three_class(tr, te, cols)),
        "binary_goalcols": suite(frame, lambda tr, te: binary(tr, te, GOAL_COLUMNS)),
        "poisson_glm": suite(frame, lambda tr, te: poisson_models(tr, te, GOAL_COLUMNS)),
        "poisson_glm_teamcols": suite(frame, lambda tr, te: poisson_models(tr, te, cols)),
    }
    res["totals_confirm"] = totals(frame, CONFIRM)
    for k, v in res.items():
        print(k, json.dumps(v))
    json.dump(res, open(args.out, "w"), indent=1)
