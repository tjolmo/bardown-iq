"""Honest model-vs-market measurement: opening/closing line comparison, market-aware stacking, betting backtest.

    python -m predictions.experiments.market [--features /scratch/feat_a.pkl /scratch/feat_b.pkl] [--cols c1 c2 ...]
                                             [--frame /scratch/team_frame.pkl] [--out /scratch/market.json]

Every model probability for season s comes from a model fitted only on seasons < s (2008+), so it is out of sample.
Market-aware stackers for test season t are fitted only on seasons 2019..t-1 of those out-of-sample probabilities.
Extra feature pickles are merged on game_id; all their non-key columns are added to the model unless --cols is given.
"""
import argparse
import json
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.linear_model import LogisticRegression
from predictions import features as F
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
try:  # production factory; its module chain needs DATABASE_URL, so fall back to an identical local copy
    from predictions.train import _team_logistic
except Exception:
    def _team_logistic():
        return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(max_iter=1000))

ODDS_FROM = 2019            # first season with odds
TEST = [2021, 2022, 2023, 2024, 2025]
RAW = ["diff_rest_days", "diff_starter_gsax60", "diff_xg5_pct_season", "diff_xg_pct_ewm", "elo_diff"]
THRESHOLDS = [0.0, 0.02, 0.04, 0.06]
RNG = np.random.default_rng(0)
B = 2000
EPS = 1e-6

logit = lambda p: np.log(np.clip(p, EPS, 1 - EPS) / (1 - np.clip(p, EPS, 1 - EPS)))
sigmoid = lambda z: 1 / (1 + np.exp(-z))
def ll_vec(y, p):
    p = np.clip(p, EPS, 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))
def decimal(american):
    a = np.asarray(american, float)
    return np.where(a > 0, 1 + a / 100, 1 + 100 / np.abs(a))

def boot_mean_ci(x, b=B):
    x = np.asarray(x, float)
    idx = RNG.integers(0, len(x), (b, len(x)))
    m = x[idx].mean(1)
    return float(x.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))

# ---------- out-of-sample model probabilities ----------

def oos_model_probs(frame, cols, seasons):
    p = pd.Series(np.nan, index=frame.index)
    for s in seasons:
        tr, te = frame[frame.season < s], frame.season == s
        p[te] = _team_logistic().fit(tr[cols], tr.home_win.astype(int)).predict_proba(frame.loc[te, cols])[:, 1]
    return p

# ---------- stackers ----------

def fit_offset_logistic(X, y, offset, l2=1.0):
    """logit(p) = offset + b0 + X b, with L2 on b (X standardized by caller). Returns coef vector incl. intercept."""
    Xa = np.c_[np.ones(len(X)), X]
    def f(w):
        z = offset + Xa @ w
        p = sigmoid(z)
        nll = ll_vec(y, p).sum() + 0.5 * l2 * (w[1:] ** 2).sum()
        g = Xa.T @ (p - y); g[1:] += l2 * w[1:]
        return nll, g
    return minimize(f, np.zeros(Xa.shape[1]), jac=True, method="L-BFGS-B").x

def stack_predictions(frame, mcol, raw_cols, tests):
    """For each test season: fit on 2019..t-1 rows where market `mcol` exists, return OOS predictions of
    S1: LR[logit mkt, logit model] (free weights), S2: offset logit mkt + L2 raw features, S3: offset + model + raw."""
    out = {k: pd.Series(np.nan, index=frame.index) for k in ["S1_mkt+model", "S2_mkt+raw", "S3_mkt+model+raw"]}
    coefs = {}
    has = frame[mcol].notna() & frame.p_model.notna()
    for t in tests:
        tr = frame[has & (frame.season >= ODDS_FROM) & (frame.season < t)]
        te_mask = has & (frame.season == t)
        te = frame[te_mask]
        if len(tr) < 500 or te.empty:
            continue
        y = tr.home_win.astype(int).to_numpy()
        lm_tr, lm_te = logit(tr[mcol].to_numpy()), logit(te[mcol].to_numpy())
        lp_tr, lp_te = logit(tr.p_model.to_numpy()), logit(te.p_model.to_numpy())
        s1 = LogisticRegression(C=1e6).fit(np.c_[lm_tr, lp_tr], y)
        out["S1_mkt+model"][te_mask] = s1.predict_proba(np.c_[lm_te, lp_te])[:, 1]
        med = tr[raw_cols].median()
        Rtr, Rte = tr[raw_cols].fillna(med), te[raw_cols].fillna(med)
        mu, sd = Rtr.mean(), Rtr.std().replace(0, 1)
        Rtr, Rte = ((Rtr - mu) / sd).to_numpy(), ((Rte - mu) / sd).to_numpy()
        w2 = fit_offset_logistic(Rtr, y, lm_tr, l2=len(tr) * 0.01)
        out["S2_mkt+raw"][te_mask] = sigmoid(lm_te + np.c_[np.ones(len(te)), Rte] @ w2)
        X3tr, X3te = np.c_[lp_tr - lm_tr, Rtr], np.c_[lp_te - lm_te, Rte]
        w3 = fit_offset_logistic(X3tr, y, lm_tr, l2=len(tr) * 0.01)
        out["S3_mkt+model+raw"][te_mask] = sigmoid(lm_te + np.c_[np.ones(len(te)), X3te] @ w3)
        coefs[t] = {"S1(mkt,model)": np.round(s1.coef_[0], 3).tolist(), "S3(model-mkt)": round(float(w3[1]), 3)}
    return out, coefs

def compare(frame, mask, ref, cand):
    """Paired by-game bootstrap of mean log-loss difference cand - ref on rows in mask."""
    d = frame[mask]
    y = d.home_win.astype(int).to_numpy()
    diff = ll_vec(y, d[cand].to_numpy()) - ll_vec(y, d[ref].to_numpy())
    m, lo, hi = boot_mean_ci(diff)
    return {"n": int(mask.sum()), "ref_ll": float(ll_vec(y, d[ref]).mean()), "cand_ll": float(ll_vec(y, d[cand]).mean()),
            "diff": m, "ci95": [lo, hi]}

# ---------- betting ----------

def backtest(frame, pcol, dh, da, label, kelly_frac=0.25):
    """Bet the side with the larger EV when EV > threshold. Flat 1u and fractional Kelly (stake = frac*kelly*100u,
    non-compounding). Returns per-threshold totals and per-season flat ROI."""
    ok = frame[pcol].notna() & np.isfinite(dh) & np.isfinite(da)
    d = frame[ok]; dh, da = dh[ok.to_numpy()], da[ok.to_numpy()]
    p = d[pcol].to_numpy(); y = d.home_win.astype(int).to_numpy()
    ev_h, ev_a = p * dh - 1, (1 - p) * da - 1
    home = ev_h >= ev_a
    ev = np.where(home, ev_h, ev_a); dec = np.where(home, dh, da)
    win = np.where(home, y == 1, y == 0)
    pnl_flat = np.where(win, dec - 1, -1.0)
    kelly = np.clip(ev / (dec - 1), 0, None) * kelly_frac
    res = {}
    for thr in THRESHOLDS:
        b = ev > thr
        if b.sum() == 0:
            res[thr] = {"bets": 0}; continue
        roi, lo, hi = boot_mean_ci(pnl_flat[b])
        stake = kelly[b] * 100
        kpnl = stake * pnl_flat[b]
        # bootstrap Kelly ROI (pnl / stake) by bet
        idx = RNG.integers(0, b.sum(), (B, b.sum()))
        kroi = kpnl[idx].sum(1) / np.maximum(stake[idx].sum(1), 1e-9)
        seasons = d.season.to_numpy()[b]
        res[thr] = {"bets": int(b.sum()), "units": float(pnl_flat[b].sum()), "roi": roi, "roi_ci95": [lo, hi],
                    "home_share": float(home[b].mean()),
                    "kelly_staked": float(stake.sum()), "kelly_units": float(kpnl.sum()),
                    "kelly_roi": float(kpnl.sum() / max(stake.sum(), 1e-9)),
                    "kelly_roi_ci95": [float(np.percentile(kroi, 2.5)), float(np.percentile(kroi, 97.5))],
                    "by_season": {int(s): {"bets": int((seasons == s).sum()), "roi": float(pnl_flat[b][seasons == s].mean())}
                                  for s in np.unique(seasons)}}
    return {label: res}

# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", default="/scratch/team_frame.pkl")
    ap.add_argument("--features", nargs="*", default=[], help="extra feature pickles merged on game_id")
    ap.add_argument("--cols", nargs="*", default=None, help="restrict extra columns (default: all non-key)")
    ap.add_argument("--raw", nargs="*", default=None, help="raw features for the market-offset stackers")
    ap.add_argument("--out", default="/scratch/market.json")
    a = ap.parse_args()

    frame = pd.read_pickle(a.frame)
    cols = [c for c in F.TEAM_FEATURE_COLUMNS if c in frame.columns]
    for path in a.features:
        extra = pd.read_pickle(path)
        new = [c for c in extra.columns if c != "game_id" and c not in frame.columns and (a.cols is None or c in a.cols)]
        frame = frame.merge(extra[["game_id"] + new], on="game_id", how="left")
        cols += [c for c in new if c not in cols]
    # production columns not in the frame or any --features pickle are skipped (features.py changes concurrently)
    missing = [c for c in F.TEAM_FEATURE_COLUMNS if c not in frame.columns]
    if missing:
        print("WARNING: production columns missing from frame/--features, skipped:", missing)
    cols = list(dict.fromkeys(cols + [c for c in F.TEAM_FEATURE_COLUMNS if c in frame.columns]))
    raw = a.raw or RAW
    frame = frame[frame.season <= max(TEST)].reset_index(drop=True)
    print(f"{len(cols)} model columns: {cols}")
    frame["p_model"] = oos_model_probs(frame, cols, range(ODDS_FROM, max(TEST) + 1))
    report = {"cols": cols, "raw": raw}

    # 1. model vs open vs close on identical games
    rows = []
    for s in sorted(frame.season[frame.mkt_open.notna()].unique()):
        d = frame[(frame.season == s) & frame.mkt.notna() & frame.mkt_open.notna()]
        y = d.home_win.astype(int).to_numpy()
        rows.append({"season": int(s), "n": len(d), "model": ll_vec(y, d.p_model).mean(),
                     "open": ll_vec(y, d.mkt_open).mean(), "close": ll_vec(y, d.mkt).mean(),
                     "corr_model_open": np.corrcoef(d.p_model, d.mkt_open)[0, 1]})
    t1 = pd.DataFrame(rows).set_index("season")
    both = frame.mkt.notna() & frame.mkt_open.notna() & frame.p_model.notna()
    print("\n== 1. log loss on games with open+close ==\n", t1.round(4).to_string())
    c_mo = compare(frame, both, "mkt_open", "p_model"); c_oc = compare(frame, both, "mkt_open", "mkt")
    print("model - open:", {k: np.round(v, 4) for k, v in c_mo.items()}, "\nclose - open:", {k: np.round(v, 4) for k, v in c_oc.items()})
    report["1_open_close"] = {"by_season": t1.reset_index().to_dict("records"), "model_minus_open": c_mo, "close_minus_open": c_oc}

    # 2. does the model add information to the market?
    report["2_stacking"] = {}
    for mcol, tests in [("mkt", TEST), ("mkt_open", [2024, 2025])]:
        preds, coefs = stack_predictions(frame, mcol, raw, tests)
        for k, v in preds.items():
            frame[f"{k}|{mcol}"] = v
        mask = frame.season.isin(tests) & frame[f"S1_mkt+model|{mcol}"].notna()
        print(f"\n== 2. vs {mcol}, test seasons {tests} (n={int(mask.sum())}); coefs {coefs}")
        r = {"model_alone": compare(frame, mask, mcol, "p_model")}
        for k in preds:
            r[k] = compare(frame, mask, mcol, f"{k}|{mcol}")
        r["by_season"] = {int(t): {k: float(compare(frame, mask & (frame.season == t), mcol, f"{k}|{mcol}")["diff"]) for k in preds}
                          for t in tests}
        for k, v in r.items():
            if k != "by_season":
                print(f"  {k:20s} ll={v['cand_ll']:.4f} mkt={v['ref_ll']:.4f} diff={v['diff']:+.4f} CI[{v['ci95'][0]:+.4f},{v['ci95'][1]:+.4f}]")
        print("  by season diff:", {t: {k: round(x, 4) for k, x in d.items()} for t, d in r["by_season"].items()})
        r["coefs"] = {int(k): v for k, v in coefs.items()}
        report["2_stacking"][mcol] = r

    # 3. betting backtest
    dh, da = decimal(frame.home_moneyline), decimal(frame.away_moneyline)
    over = 1 / dh + 1 / da
    # stored medians contain corrupt prices (e.g. -2.5, 0, -0.5: books mixing +100/-100 conventions), which pay
    # 40x and dominate any ROI. Keep only |price| >= 100 with a sane overround and vig-free prob matching `mkt`.
    nv = (1 / dh) / over
    valid = ((frame.home_moneyline.abs() >= 100) & (frame.away_moneyline.abs() >= 100) & (over >= 1.0) & (over <= 1.10)
             & ((nv - frame.mkt).abs() < 0.02)).to_numpy()
    in_test = frame.season.isin(TEST).to_numpy() & frame.mkt.notna().to_numpy()
    print(f"\ninvalid closing prices dropped: {int((in_test & ~valid).sum())} of {int(in_test.sum())} test games")
    dh, da, over = np.where(valid, dh, np.nan), np.where(valid, da, np.nan), np.where(valid, over, np.nan)
    print(f"close overround median {np.nanmedian(over):.4f}")
    report["invalid_prices_dropped"] = int((in_test & ~valid).sum())
    # real opening prices (stored from 2023-24 on)
    oh, oa = decimal(frame.open_home_moneyline), decimal(frame.open_away_moneyline)
    test_rows = frame.season.isin(TEST).to_numpy()
    nan = lambda x: np.where(test_rows, x, np.nan)
    bt = {}
    bt.update(backtest(frame, "p_model", nan(dh), nan(da), "model@close"))
    bt.update(backtest(frame, "S1_mkt+model|mkt", nan(dh), nan(da), "S1blend@close"))
    bt.update(backtest(frame, "p_model", nan(oh), nan(oa), "model@open"))
    bt.update(backtest(frame, "S1_mkt+model|mkt_open", nan(oh), nan(oa), "S1blend@open"))
    print("\n== 3. betting (flat 1u / quarter Kelly per 100u) ==")
    for label, res in bt.items():
        for thr, r in res.items():
            if not r["bets"]:
                print(f"  {label:22s} thr={thr:.2f} no bets"); continue
            print(f"  {label:22s} thr={thr:.2f} bets={r['bets']:5d} units={r['units']:+7.1f} ROI={r['roi']:+.3f} "
                  f"CI[{r['roi_ci95'][0]:+.3f},{r['roi_ci95'][1]:+.3f}] kellyROI={r['kelly_roi']:+.3f} "
                  f"CI[{r['kelly_roi_ci95'][0]:+.3f},{r['kelly_roi_ci95'][1]:+.3f}] "
                  f"seasons={ {s: round(v['roi'], 3) for s, v in r['by_season'].items()} }")
    report["3_betting"] = {k: {str(t): v for t, v in r.items()} for k, r in bt.items()}
    report["close_overround_median"] = float(np.nanmedian(over))
    with open(a.out, "w") as f:
        json.dump(report, f, indent=1, default=float)
    print("\nwrote", a.out)

if __name__ == "__main__":
    main()
