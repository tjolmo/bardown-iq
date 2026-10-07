"""Is the out-of-sample dispersion right? Scores props_models' test-season predictions as count distributions.

For each target and test season, compares pricing the same predicted means as:
- poisson: alpha 0
- legacy: config.PROP_DISPERSION (hand-set on the props-v2 test seasons, so in sample here)
- fitted: the alpha props_models fitted on the fold's early-stopping season (`alpha_{variant}_{target}`), i.e. what
  nightly training does on its validation split; the test season never informs it
- oracle: the alpha fitted on the test season itself (an upper bound; the gap to it is the selection optimism an
  in-sample alpha carries)
Scores: mean NB log likelihood per row, and P(over) log loss at the half-point line nearest each row's mean (where
book lines sit) and at 0.5, with the calibration of P(over) at the near-mean line.

    python -m predictions.experiments.dispersion_eval --skater-preds /app/.../props_preds_skater.pkl --variant +shares+teammates \
        --goalie-preds /app/.../props_preds_goalie.pkl --goalie-variant +market_2008 [--out report.json]
"""
import argparse
import json
import numpy as np
import pandas as pd
from predictions.config import PROP_DISPERSION
from predictions.dispersion import fit_alpha, nb2_loglik
from predictions.experiments.props_benchmark import p_over, ll_vec


def near_line(mu):
    """The half-point line nearest the mean (book lines sit near the median of the count)."""
    return np.maximum(np.round(np.asarray(mu) - 0.5) + 0.5, 0.5)


def score(y, mu, alpha, line) -> dict:
    p = p_over(mu, line, alpha)
    yy = (y > line).astype(int)
    return {"loglik": float(nb2_loglik(y, mu, float(alpha)).mean()), "p_over_logloss": float(ll_vec(yy, p).mean()),
            "mean_p": float(p.mean()), "over_rate": float(yy.mean())}


def evaluate(frame: pd.DataFrame, variant: str, targets) -> dict:
    out = {}
    for t in targets:
        pcol, acol = f"pred_{variant}_{t}", f"alpha_{variant}_{t}"
        if pcol not in frame or t not in frame:
            continue
        res = {}
        for season, d in frame[frame[t].notna() & frame[pcol].notna()].groupby("season"):
            y, mu = d[t].to_numpy(float), d[pcol].to_numpy(float)
            oracle = fit_alpha(y, mu)
            alphas = {"poisson": 0.0, "legacy": PROP_DISPERSION.get(t, 0.0),
                      "fitted": float(d[acol].iloc[0]) if acol in d else np.nan, "oracle": oracle["alpha_mle"]}
            r = {"rows": len(d), "alpha": alphas, "oracle_fit": oracle}
            for line_name, line in (("near_mean", near_line(mu)), ("0.5", np.full(len(mu), 0.5))):
                r[line_name] = {k: score(y, mu, a, line) for k, a in alphas.items() if np.isfinite(a)}
            line = near_line(mu)
            q = pd.qcut(mu, 5, duplicates="drop")
            r["calibration_near_mean"] = {
                k: pd.DataFrame({"p": p_over(mu, line, a), "y": (y > line).astype(int)}).groupby(q, observed=True)
                .mean().round(3).values.tolist() for k, a in alphas.items() if np.isfinite(a)}
            res[int(season)] = r
        out[t] = res
        show(t, res)
    return out


def show(t, res):
    print(f"== {t}")
    for season, r in res.items():
        a = r["alpha"]
        print(f"  {season}: n={r['rows']}  alpha fitted {a['fitted']:.4f} (oracle {a['oracle']:.4f}, legacy {a['legacy']:.2f}, "
              f"oracle mom {r['oracle_fit']['alpha_mom']:.4f})")
        print("    loglik/row           " + "  ".join(f"{k} {v['loglik']:.5f}" for k, v in r["near_mean"].items()))
        for line_name in ("near_mean", "0.5"):
            print(f"    P(over) @{line_name:<9s}    " + "  ".join(
                f"{k} {v['p_over_logloss']:.5f}" for k, v in r[line_name].items()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skater-preds", nargs="*", default=[])
    ap.add_argument("--variant", default="+shares+teammates")
    ap.add_argument("--goalie-preds", nargs="*", default=[])
    ap.add_argument("--goalie-variant", default="+market_2008")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    report = {}
    for path in args.skater_preds:
        f = pd.read_pickle(path)
        report.update(evaluate(f, args.variant, ["goals", "assists", "points", "shots_on_goal", "hits",
                                                 "blocked_shots", "pp_points"]))
    for path in args.goalie_preds:
        f = pd.read_pickle(path)
        report.update({f"goalie_{k}": v for k, v in evaluate(f, args.goalie_variant, ["goals_against", "sog", "saves"]).items()})
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(report, fh, indent=1, default=float)


if __name__ == "__main__":
    main()
