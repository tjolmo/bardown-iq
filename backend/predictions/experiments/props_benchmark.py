"""Benchmark the player models against prop prices.

Model probabilities are out of sample: they come from props_models.py, whose per-season models never saw the
season they predict. For each two-sided market (over/under a line) the model's P(over) = P(X > line) under its
Poisson rate is compared with the book's vig-free probability. One-sided markets (anytime goal = P(goals >= 1))
are scored against the raw implied probability (margin included) and get a betting backtest at their price.

The vig-free market probability depends on how the margin is removed (predictions/vig.py). The market's own log
loss is computed under every method for each prop type: the method with the lowest market log loss is the one
that best recovers the true probabilities, and `--vig` (default: the overall best) is used for model vs market.

Sources:
- default: ESPN history in `player_prop_odds` (one book per era).
- `--quotes`: multi-book quotes in `prop_quotes` (PropLine; the Odds API before Oct 2026). The market is the
  consensus line (most books; lower line on a tie), its fair P(over) the mean of each book's vig-free P(over) at
  that line, and bets are priced at the best available price at that line.

    python -m predictions.experiments.props_benchmark --variant +market+sog/pp_2008 \
        --skater-preds /scratch/props_preds_skater_trend.pkl /scratch/props_preds_skater.pkl [--vig shin] [--quotes]
Several skater prediction files can be given; for each target the first file holding the prediction column wins.
Dispersion: Poisson by default; `--alpha hits=0.12 ...` fixes a stat's negative-binomial alpha, and `--fitted-alpha`
prices each row with the alpha props_models fitted on that fold's early-stopping season (`alpha_{variant}_{target}`).
"""
import argparse
import asyncio
import json
import numpy as np
import pandas as pd
from scipy.stats import poisson, nbinom
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import PlayerPropOdds, Games, PropQuote
from predictions.vig import METHODS, devig_two_way, implied_prob, american_to_decimal as decimal

# prop_type slug -> (model target column, which predictions file, fixed line for one-sided markets or None)
PROP_TARGETS = {"goals": ("goals", "skater", None), "assists": ("assists", "skater", None),
                "points": ("points", "skater", None), "shots_on_goal": ("shots_on_goal", "skater", None),
                "hits": ("hits", "skater", None), "blocked_shots": ("blocked_shots", "skater", None),
                "pp_points": ("pp_points", "skater", None), "anytime_goal": ("goals", "skater", 0.5),
                "saves": ("saves", "goalie", None), "goals_against": ("goals_against", "goalie", None)}
# prop_quotes market key (Odds API style) -> prop_type slug above
QUOTE_PROP_TYPES = {"player_points": "points", "player_assists": "assists", "player_goals": "goals",
                       "player_shots_on_goal": "shots_on_goal", "player_blocked_shots": "blocked_shots",
                       "player_power_play_points": "pp_points", "player_total_saves": "saves",
                       "player_goal_scorer_anytime": "anytime_goal"}
DEFAULT_VIG = "shin"    # ties additive (identical for these two-way markets) for the lowest market log loss on the ESPN history (goals: shin 0.3898 vs multiplicative 0.3933)
THRESHOLDS = [0.0, 0.02, 0.05, 0.08]
P_CLIP = 1e-4
rng = np.random.default_rng(0)


def boot_ci(x, b=2000):
    x = np.asarray(x, float)
    if len(x) < 2:
        return [np.nan, np.nan]
    means = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(b)]
    return [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]


def ll_vec(y, p):
    p = np.clip(p, P_CLIP, 1 - P_CLIP)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


async def _load_props():
    async with AsyncSessionLocal() as db:
        stmt = select(PlayerPropOdds.game_id, PlayerPropOdds.player_id, PlayerPropOdds.prop_type, PlayerPropOdds.line,
                      PlayerPropOdds.book, PlayerPropOdds.over_price, PlayerPropOdds.under_price, PlayerPropOdds.open_line,
                      PlayerPropOdds.open_over_price, PlayerPropOdds.open_under_price, PlayerPropOdds.sides_inferred,
                      Games.season).join(Games, Games.id == PlayerPropOdds.game_id)
        df = pd.DataFrame([dict(r) for r in (await db.execute(stmt)).mappings().all()])
    df["season"] = df["season"] // 10000
    return df


async def _load_quotes():
    async with AsyncSessionLocal() as db:
        stmt = (select(PropQuote, Games.season, Games.start_time)
                .join(Games, Games.id == PropQuote.game_id))
        rows = (await db.execute(stmt)).all()
    cols = [c.name for c in PropQuote.__table__.columns]
    df = pd.DataFrame([{**{c: getattr(q, c) for c in cols}, "season": s, "start_time": t} for q, s, t in rows],
                      columns=cols + ["season", "start_time"])
    df["season"] = df["season"] // 10000
    return df


def consensus_markets(quotes: pd.DataFrame, method: str) -> pd.DataFrame:
    """Multi-book quotes -> one market per (game, player, prop): consensus line, best over/under price at it, and
    the mean of the books' vig-free P(over) at that line (books quoting both sides) as the market probability."""
    out_cols = ["game_id", "player_id", "prop_type", "season", "line", "over_price", "under_price",
                "market_p", "n_books", "open_line", "open_over_price", "open_under_price", "sides_inferred"]
    q = quotes.copy()
    if "start_time" in q:   # pre-game quotes only (both feeds only list upcoming games anyway)
        q = q[pd.to_datetime(q["last_seen"], utc=True) <= pd.to_datetime(q["start_time"], utc=True)]
    q["prop_type"] = q["prop_type"].map(lambda k: QUOTE_PROP_TYPES.get(k, k))
    q["side"] = np.where(q["over_under"].str.lower().isin(["over", "yes"]), "over",
                         np.where(q["over_under"].str.lower() == "under", "under", None))
    q = q[q["side"].notna()]
    if q.empty:
        return pd.DataFrame(columns=out_cols)
    key = ["game_id", "player_id", "prop_type"]
    books_per_line = q.groupby(key + ["line"])["bookmaker"].nunique().rename("n").reset_index()
    books_per_line = books_per_line.sort_values(key + ["n", "line"], ascending=[True] * 3 + [False, True])
    cons = books_per_line.drop_duplicates(key)[key + ["line"]]
    at = q.merge(cons, on=key + ["line"])
    wide = at.pivot_table(index=key + ["season", "line", "bookmaker"], columns="side", values="odds", aggfunc="max")
    wide = wide.reindex(columns=["over", "under"]).reset_index()
    both = wide["over"].notna() & wide["under"].notna()
    wide["fair_over"] = np.nan
    if both.any():
        wide.loc[both, "fair_over"] = devig_two_way(wide.loc[both, "over"], wide.loc[both, "under"], method)
    g = wide.groupby(key + ["season", "line"])
    m = pd.DataFrame({"over_price": g["over"].max(), "under_price": g["under"].max(),
                      "market_p": g["fair_over"].mean(), "n_books": g["bookmaker"].nunique()}).reset_index()
    m["open_line"] = np.nan
    m["open_over_price"] = np.nan
    m["open_under_price"] = np.nan
    m["sides_inferred"] = False
    return m[out_cols]


def p_over(lam, line, alpha=0.0):
    """P(X > line) for a Poisson count, or a negative binomial with variance mu(1 + alpha mu) where alpha > 0
    (alpha: a scalar or one per row)."""
    lam, k = np.asarray(lam, float), np.floor(np.asarray(line, float))
    alpha = np.broadcast_to(np.asarray(alpha, float), np.broadcast(lam, k).shape)
    n = 1 / np.where(alpha > 0, alpha, 1.0)
    return np.where(alpha > 0, 1 - nbinom.cdf(k, n, n / (n + lam)), 1 - poisson.cdf(k, lam))


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


def find_preds(pred_frames, target, pcol):
    """First predictions frame holding both the actual target column and the prediction column."""
    for frame in pred_frames:
        if pcol in frame and target in frame:
            return frame
    return None


def evaluate(df, p_model, y, method, two_sided, one_line):
    """Scores one prop type. df holds over/under prices (+ optional open prices and market_p for quote markets)."""
    r = {"rows": len(df)}
    two = (df["over_price"].notna() & df["under_price"].notna()).to_numpy() if two_sided else np.zeros(len(df), bool)
    if two.any():
        d2, pm, yy = df[two], p_model[two], y[two]
        ll_m = ll_vec(yy, pm)
        by_method = {m: devig_two_way(d2["over_price"], d2["under_price"], m) for m in METHODS}
        mkt_ll = {m: ll_vec(yy, p) for m, p in by_method.items()}
        p_mkt = by_method[method]
        if "market_p" in d2:   # multi-book consensus (already de-vigged with `method`) where available
            p_mkt = np.where(d2["market_p"].notna(), d2["market_p"].to_numpy(float), p_mkt)
        ll_k = ll_vec(yy, p_mkt)
        r["two_sided"] = {
            "n": int(two.sum()), "vig_method": method, "model_logloss": round(float(ll_m.mean()), 4),
            "market_logloss": round(float(ll_k.mean()), 4), "diff": round(float((ll_m - ll_k).mean()), 4),
            "diff_ci95": boot_ci(ll_m - ll_k), "model_mean_p": round(float(np.mean(pm)), 4),
            "market_mean_p": round(float(np.mean(p_mkt)), 4), "actual_over_rate": round(float(yy.mean()), 4),
            "market_logloss_by_vig": {m: round(float(v.mean()), 5) for m, v in mkt_ll.items()},
            "market_mean_p_by_vig": {m: round(float(p.mean()), 4) for m, p in by_method.items()},
            # each method's market log loss minus the best method's, with a paired bootstrap CI
            "vig_gap_vs_best": {}}
        best = min(mkt_ll, key=lambda m: mkt_ll[m].mean())
        r["two_sided"]["best_vig"] = best
        for m in METHODS:
            if m != best:
                d = mkt_ll[m] - mkt_ll[best]
                r["two_sided"]["vig_gap_vs_best"][m] = [round(float(d.mean()), 5)] + [round(c, 5) for c in boot_ci(d, 500)]
        q = pd.qcut(np.clip(pm, P_CLIP, 1 - P_CLIP), 5, duplicates="drop")
        r["two_sided"]["calibration"] = pd.DataFrame({"p": pm, "y": yy}).groupby(q, observed=True).mean().round(3).values.tolist()
    bt = {}
    if two.any():
        bets(df[two], p_model[two], "over_price", "under_price", "close", bt)
        same_open = two & (df["open_line"] == df["line"]).to_numpy() & df["open_over_price"].notna().to_numpy() \
            & df["open_under_price"].notna().to_numpy()
        if same_open.any():
            bets(df[same_open], p_model[same_open], "open_over_price", "open_under_price", "open_same_line", bt)
    one = df["over_price"].notna().to_numpy() & ~two
    if one.any():
        d1, p1, y1 = df[one].assign(under_price=np.nan), p_model[one], y[one]
        raw = implied_prob(d1["over_price"])
        ll_m, ll_raw = ll_vec(y1, p1), ll_vec(y1, raw)
        r["one_sided"] = {"n": int(one.sum()), "line": one_line, "model_logloss": round(float(ll_m.mean()), 4),
                          "raw_implied_logloss": round(float(ll_raw.mean()), 4),
                          "model_mean_p": round(float(p1.mean()), 4), "raw_implied_mean_p": round(float(raw.mean()), 4),
                          "actual_rate": round(float(y1.mean()), 4)}
        bets(d1, p1, "over_price", "under_price", "one_sided_close", bt)
    r["betting"] = bt
    return r


def print_result(prop_type, r):
    print(f"\n== {prop_type}: {r['rows']} rows ({r.get('matched_share', 1):.0%} matched to predictions)")
    if "two_sided" in r:
        t = r["two_sided"]
        lls = "  ".join(f"{m}={v:.5f}" for m, v in t["market_logloss_by_vig"].items())
        print(f"   market log loss by vig: {lls}  -> best {t['best_vig']}")
        print(f"   two-sided n={t['n']} [{t['vig_method']}] model {t['model_logloss']} vs market {t['market_logloss']} "
              f"diff {t['diff']:+.4f} CI[{t['diff_ci95'][0]:+.4f},{t['diff_ci95'][1]:+.4f}]  mean p model "
              f"{t['model_mean_p']} market {t['market_mean_p']} actual {t['actual_over_rate']}")
    if "one_sided" in r:
        o = r["one_sided"]
        print(f"   one-sided n={o['n']} model {o['model_logloss']} vs raw implied {o['raw_implied_logloss']}  mean p "
              f"model {o['model_mean_p']} implied {o['raw_implied_mean_p']} actual {o['actual_rate']}")
    for label, res in r["betting"].items():
        for thr, b in res.items():
            if b["bets"]:
                print(f"   {label:<16s} thr={thr:.2f} bets={b['bets']:6d} units={b['units']:+8.1f} ROI={b['roi']:+.3f} "
                      f"CI[{b['ci95'][0]:+.3f},{b['ci95'][1]:+.3f}] {b['by_season']}")


def run(props, preds, variants, method, alphas, only=None, fitted_alpha=False):
    report = {}
    for prop_type, (target, kind, one_line) in PROP_TARGETS.items():
        if only and prop_type not in only:
            continue
        sub = props[props["prop_type"] == prop_type]
        pcol = f"pred_{variants[kind]}_{target}"
        frame = find_preds(preds[kind], target, pcol)
        if sub.empty or frame is None:
            if not sub.empty:
                print(f"\n== {prop_type}: {len(sub)} rows, no predictions column {pcol!r}; skipped")
            continue
        acol = f"alpha_{variants[kind]}_{target}"
        if fitted_alpha and acol not in frame:
            print(f"\n== {prop_type}: no fitted alpha column {acol!r}; priced as Poisson")
        pr = frame[["game_id", "player_id", target, pcol] + ([acol] if fitted_alpha and acol in frame else [])]
        pr = pr.rename(columns={target: "actual", pcol: "lam", acol: "alpha"})
        df = sub.merge(pr, on=["game_id", "player_id"]).dropna(subset=["actual", "lam"]).reset_index(drop=True)
        if df.empty:
            continue
        df["line_used"] = one_line if one_line is not None else df["line"]
        # a whole-number line that lands exactly is a push (stake back): neither side's outcome, so leave it out
        df = df[df["actual"] != df["line_used"]].reset_index(drop=True)
        alpha = df["alpha"].to_numpy(float) if "alpha" in df else alphas.get(target, 0.0)
        p_model = p_over(df["lam"].to_numpy(), df["line_used"].to_numpy(float), alpha)
        y = (df["actual"] > df["line_used"]).astype(int).to_numpy()
        r = evaluate(df, p_model, y, method, two_sided=one_line is None, one_line=one_line)
        r["matched_share"] = round(len(df) / len(sub), 3)
        report[prop_type] = r
        print_result(prop_type, r)
    # pooled market log loss per vig method across two-sided prop types (weighted by lines)
    pooled = {}
    for m in METHODS:
        num = sum(r["two_sided"]["market_logloss_by_vig"][m] * r["two_sided"]["n"] for r in report.values() if "two_sided" in r)
        den = sum(r["two_sided"]["n"] for r in report.values() if "two_sided" in r)
        if den:
            pooled[m] = round(num / den, 5)
    if pooled:
        report["_pooled_market_logloss_by_vig"] = pooled
        print(f"\npooled market log loss by vig method: {pooled} -> best {min(pooled, key=pooled.get)}")
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="+market_2008", help="skater prediction variant")
    ap.add_argument("--goalie-variant", default="+market_2008")
    ap.add_argument("--out", default="/scratch/props_benchmark.json")
    ap.add_argument("--skater-preds", nargs="+", default=["/scratch/props_preds_skater.pkl"],
                    help="one or more skater prediction pickles; the first holding a target's column is used")
    ap.add_argument("--goalie-preds", nargs="+", default=["/scratch/props_preds_goalie.pkl"])
    ap.add_argument("--vig", choices=METHODS, default=DEFAULT_VIG, help="vig removal for the market probability")
    ap.add_argument("--quotes", action="store_true", help="multi-book prop_quotes (PropLine) instead of ESPN history")
    ap.add_argument("--alpha", nargs="*", default=[], help="stat=alpha negative-binomial dispersion, e.g. shots_on_goal=0.06")
    ap.add_argument("--fitted-alpha", action="store_true",
                    help="price with the out-of-sample alphas saved by props_models (overrides --alpha)")
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()
    if args.quotes:
        quotes = asyncio.run(_load_quotes())
        props = consensus_markets(quotes, args.vig)
        print(f"prop_quotes: {len(quotes)} rows -> {len(props)} consensus markets")
        if props.empty:
            with open(args.out, "w") as f:
                json.dump({"source": "prop_quotes", "quotes": len(quotes), "markets": 0}, f)
            return
    else:
        props = asyncio.run(_load_props())
    print("prop rows by type:", props.groupby("prop_type").size().to_dict())
    alphas = {k: float(v) for k, v in (a.split("=") for a in args.alpha)}
    preds = {"skater": [pd.read_pickle(p) for p in args.skater_preds],
             "goalie": [pd.read_pickle(p) for p in args.goalie_preds]}
    report = run(props, preds, {"skater": args.variant, "goalie": args.goalie_variant}, args.vig, alphas, args.only,
                 args.fitted_alpha)
    report["_source"] = "prop_quotes" if args.quotes else "player_prop_odds"
    with open(args.out, "w") as f:
        json.dump(report, f, indent=1, default=float)


if __name__ == "__main__":
    main()
