"""Benchmark the player models against ESPN prop prices (2023-24 onward).

Model probabilities are out of sample: they come from props_models.py, whose per-season models never saw the
season they predict. For each two-sided market (over/under a line) the model's P(over) = P(X > line) under its
Poisson rate is compared with the book's vig-free probability; one-sided markets (anytime goal, "N+" milestones)
only get a betting backtest against their price.
    python -m predictions.experiments.props_benchmark [--variant +market_2008]
"""
import argparse
import asyncio
import json
import numpy as np
import pandas as pd
from scipy.stats import poisson, nbinom
from sklearn.metrics import log_loss
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import PlayerPropOdds, Games

# prop_type slug -> (model target column, which predictions file)
PROP_TARGETS = {"goals": ("goals", "skater"), "assists": ("assists", "skater"), "points": ("points", "skater"),
                "shots_on_goal": ("shots_on_goal", "skater"), "saves": ("saves", "goalie"),
                "goals_against": ("goals_against", "goalie")}
THRESHOLDS = [0.0, 0.02, 0.05, 0.08]
rng = np.random.default_rng(0)

def decimal(american):
    a = np.asarray(american, float)
    return np.where(a > 0, 1 + a / 100, 1 + 100 / np.abs(a))

def boot_ci(x, b=2000):
    x = np.asarray(x, float)
    if len(x) < 2:
        return [np.nan, np.nan]
    means = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(b)]
    return [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]

async def _load_props():
    async with AsyncSessionLocal() as db:
        stmt = select(PlayerPropOdds.game_id, PlayerPropOdds.player_id, PlayerPropOdds.prop_type, PlayerPropOdds.line,
                      PlayerPropOdds.book, PlayerPropOdds.over_price, PlayerPropOdds.under_price, PlayerPropOdds.open_line,
                      PlayerPropOdds.open_over_price, PlayerPropOdds.open_under_price, PlayerPropOdds.sides_inferred,
                      Games.season).join(Games, Games.id == PlayerPropOdds.game_id)
        df = pd.DataFrame([dict(r) for r in (await db.execute(stmt)).mappings().all()])
    df["season"] = df["season"] // 10000
    return df

def p_over(lam, line, alpha=0.0):
    """P(X > line) for a Poisson count, or a negative binomial with variance mu(1 + alpha mu) when alpha > 0."""
    if alpha > 0:
        n = 1 / alpha
        return 1 - nbinom.cdf(np.floor(line), n, n / (n + lam))
    return 1 - poisson.cdf(np.floor(line), lam)

def bets(df, p_model, over_col, under_col, label, out):
    """Flat 1-unit bets on whichever side the model thinks beats the price by more than the threshold."""
    d_over, d_under = decimal(df[over_col]), decimal(df[under_col])
    won_over = df["actual"].to_numpy() > df["line_used"].to_numpy()
    push = df["actual"].to_numpy() == df["line_used"].to_numpy()
    res = {}
    for thr in THRESHOLDS:
        edge_over = p_model * d_over - 1
        edge_under = (1 - p_model) * d_under - 1
        take_over = (edge_over > thr) & (edge_over >= np.nan_to_num(edge_under, nan=-9)) & np.isfinite(d_over)
        take_under = (edge_under > thr) & ~take_over & np.isfinite(d_under)
        pnl = np.where(take_over, np.where(push, 0, np.where(won_over, d_over - 1, -1)), 0.0)
        pnl = pnl + np.where(take_under, np.where(push, 0, np.where(~won_over, d_under - 1, -1)), 0.0)
        taken = take_over | take_under
        r = pnl[taken]
        by_season = {int(s): round(float(pnl[taken & (df["season"].to_numpy() == s)].mean()), 4)
                     for s in sorted(df["season"].unique()) if (taken & (df["season"].to_numpy() == s)).any()}
        res[thr] = {"bets": int(taken.sum()), "units": round(float(r.sum()), 1),
                    "roi": round(float(r.mean()), 4) if len(r) else None, "ci95": boot_ci(r) if len(r) else None,
                    "by_season": by_season}
    out[label] = res

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="+market_2008")
    ap.add_argument("--out", default="/scratch/props_benchmark.json")
    ap.add_argument("--skater-preds", default="/scratch/props_preds_skater.pkl")
    ap.add_argument("--alpha", nargs="*", default=[], help="stat=alpha negative-binomial dispersion, e.g. shots_on_goal=0.06")
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()
    props = asyncio.run(_load_props())
    print("prop rows by type:", props.groupby("prop_type").size().to_dict())
    alphas = {k: float(v) for k, v in (a.split("=") for a in args.alpha)}
    preds = {"skater": pd.read_pickle(args.skater_preds),
             "goalie": pd.read_pickle("/scratch/props_preds_goalie.pkl")}
    report = {}
    for prop_type, (target, kind) in PROP_TARGETS.items():
        if args.only and prop_type not in args.only:
            continue
        sub = props[props["prop_type"] == prop_type]
        pcol = f"pred_{args.variant}_{target}"
        if sub.empty or pcol not in preds[kind]:
            continue
        pr = preds[kind][["game_id", "player_id", target, pcol]].rename(columns={target: "actual", pcol: "lam"})
        df = sub.merge(pr, on=["game_id", "player_id"])
        if df.empty:
            continue
        df["line_used"] = df["line"]
        p_model = p_over(df["lam"].to_numpy(), df["line"].to_numpy(), alphas.get(target, 0.0))
        y = (df["actual"] > df["line"]).astype(int).to_numpy()
        r = {"rows": len(df), "matched_share": round(len(df) / len(sub), 3)}
        two = df["over_price"].notna() & df["under_price"].notna()
        if two.any():
            io, iu = 1 / decimal(df.loc[two, "over_price"]), 1 / decimal(df.loc[two, "under_price"])
            p_mkt = io / (io + iu)
            pm, yy = np.clip(p_model[two.to_numpy()], 1e-4, 1 - 1e-4), y[two.to_numpy()]
            ll_m = -(yy * np.log(pm) + (1 - yy) * np.log(1 - pm))
            ll_k = -(yy * np.log(p_mkt) + (1 - yy) * np.log(1 - p_mkt))
            r["two_sided"] = {"n": int(two.sum()), "model_logloss": round(float(ll_m.mean()), 4),
                              "market_logloss": round(float(ll_k.mean()), 4),
                              "diff": round(float((ll_m - ll_k).mean()), 4), "diff_ci95": boot_ci(ll_m - ll_k),
                              "model_mean_p": round(float(pm.mean()), 4), "market_mean_p": round(float(p_mkt.mean()), 4),
                              "actual_over_rate": round(float(yy.mean()), 4)}
            # calibration of model P(over) in deciles
            q = pd.qcut(pm, 5, duplicates="drop")
            r["two_sided"]["calibration"] = pd.DataFrame({"p": pm, "y": yy}).groupby(q, observed=True).mean().round(3).values.tolist()
        bt = {}
        bets(df[two], p_model[two.to_numpy()], "over_price", "under_price", "close", bt)
        same_open = two & (df["open_line"] == df["line"]) & df["open_over_price"].notna() & df["open_under_price"].notna()
        if same_open.any():
            bets(df[same_open], p_model[same_open.to_numpy()], "open_over_price", "open_under_price", "open_same_line", bt)
        one = df["over_price"].notna() & df["under_price"].isna()
        if one.any():
            sub1 = df[one].assign(under_price=np.nan)
            bets(sub1, p_model[one.to_numpy()], "over_price", "under_price", "one_sided_close", bt)
        r["betting"] = bt
        report[prop_type] = r
        print(f"\n== {prop_type}: {r['rows']} rows ({r['matched_share']:.0%} matched to predictions)")
        if "two_sided" in r:
            t = r["two_sided"]
            print(f"   two-sided n={t['n']} model {t['model_logloss']} vs market {t['market_logloss']} diff {t['diff']:+.4f} "
                  f"CI[{t['diff_ci95'][0]:+.4f},{t['diff_ci95'][1]:+.4f}]  mean p model {t['model_mean_p']} market "
                  f"{t['market_mean_p']} actual {t['actual_over_rate']}")
        for label, res in bt.items():
            for thr, b in res.items():
                if b["bets"]:
                    print(f"   {label:<16s} thr={thr:.2f} bets={b['bets']:6d} units={b['units']:+8.1f} ROI={b['roi']:+.3f} "
                          f"CI[{b['ci95'][0]:+.3f},{b['ci95'][1]:+.3f}] {b['by_season']}")
    with open(args.out, "w") as f:
        json.dump(report, f, indent=1, default=float)

if __name__ == "__main__":
    main()
