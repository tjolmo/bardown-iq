"""Player models with market context: do market-implied team goals and the opposing starter help?
Out of time: test 2024-25 (train ..2022, early-stop 2023) and 2025-26 (train ..2023, early-stop 2024).
    python -m predictions.experiments.props_models [--targets goals assists points shots_on_goal hits blocked_shots pp_points] [--goalies]
Writes per-row out-of-sample predictions to /scratch/props_preds_{skater,goalie}.pkl for the prop benchmark.
"""
import argparse
import asyncio
import json
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, mean_poisson_deviance
from sqlalchemy import select
from xgboost import XGBRegressor
from app.database import AsyncSessionLocal
from app.models import GameOdds
from predictions import features as F
from predictions.config import POISSON_PARAMS, GOALIE_POISSON_PARAMS
from predictions.train import _recency_weights
from predictions.data import load_skater_logs, load_goalie_logs, load_team_stats, load_games

FOLDS = [(2023, 2024), (2024, 2025)]       # (early-stopping season, test season)
FAST = {"learning_rate": 0.05, "early_stopping_rounds": 60}   # relative comparisons only

async def _load():
    async with AsyncSessionLocal() as db:
        odds = pd.DataFrame([dict(r) for r in (await db.execute(
            select(GameOdds.game_id, GameOdds.home_prob_novig, GameOdds.total_line))).mappings().all()])
        return (await load_skater_logs(db), await load_goalie_logs(db), await load_team_stats(db),
                await load_games(db), odds)

def context(team_stats, games, goalies, odds):
    team_games = F.build_team_games(team_stats)
    tf = F.team_history_features(team_games)
    tf = tf.merge(F.implied_team_goals(games, odds), on=["game_id", "team"], how="left")
    st = F.starter_features(team_games, goalies).rename(columns={"starter_gsax60": "team_starter_gsax60"})
    return tf.merge(st, on=["game_id", "team"], how="left")

def run(df, targets, variants, params, trend=None):
    out, preds = {}, []
    for valid_s, test_s in FOLDS:
        va, te = df[df.season == valid_s], df[df.season == test_s].copy()
        for name, (cols, start, *rest) in variants.items():
            half_life = rest[0] if rest else None
            tr = df[(df.season >= start) & (df.season < valid_s)]
            for t in targets:
                margin = f"trend_{t}" if trend and t in trend else None
                bm = lambda d: np.log(d[margin].to_numpy()) if margin else None
                trt, vat = tr[tr[t].notna()], va[va[t].notna()]     # a few old rows lack newer stats
                m = XGBRegressor(**(params | FAST))
                m.fit(trt[cols].astype(np.float32), trt[t], base_margin=bm(trt), eval_set=[(vat[cols].astype(np.float32), vat[t])],
                      base_margin_eval_set=[bm(vat)] if margin else None, verbose=False,
                      sample_weight=_recency_weights(trt["date"], half_life))
                mu_va = m.predict(vat[cols].astype(np.float32), base_margin=bm(vat))
                mu_all = m.predict(te[cols].astype(np.float32), base_margin=bm(te))
                te[f"pred_{name}_{t}"] = mu_all
                ok = te[t].notna().to_numpy()
                mu, y = mu_all[ok], te[t].to_numpy()[ok]
                r = {"dev": mean_poisson_deviance(y, np.clip(mu, 1e-6, None)),
                     "p1_logloss": log_loss((y >= 1).astype(int), np.clip(1 - np.exp(-mu), 1e-6, 1 - 1e-6), labels=[0, 1]),
                     "valid_dev": mean_poisson_deviance(vat[t], np.clip(mu_va, 1e-6, None)), "trees": m.best_iteration + 1}
                out.setdefault(name, {}).setdefault(t, {})[test_s] = r
        preds.append(te)
    return out, pd.concat(preds)

def show(out, targets):
    for t in targets:
        print(f"== {t}")
        for name, res in out.items():
            r = res[t]
            print(f"  {name:<28s} dev " + " ".join(f"{s}:{r[s]['dev']:.4f}" for s in r)
                  + f"  mean {np.mean([v['dev'] for v in r.values()]):.4f} | P(>=1) logloss mean "
                  f"{np.mean([v['p1_logloss'] for v in r.values()]):.4f} | valid dev "
                  + " ".join(f"{s - 1}:{r[s]['valid_dev']:.4f}" for s in r), flush=True)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", nargs="+", default=["goals", "assists", "points"])
    ap.add_argument("--goalies", action="store_true")
    ap.add_argument("--skater-trend", nargs="*", default=[], help="skater targets that get the league-trend base margin")
    ap.add_argument("--variants", nargs="*", default=None)
    ap.add_argument("--preds-out", help="predictions pickle path (default /scratch/props_preds_{skater,skater_trend,goalie}.pkl); "
                    "the JSON report goes next to it with a .json suffix")
    ap.add_argument("--half-lives", nargs="*", type=float, default=[],
                    help="also run the last variant with recency sample weights of these half-lives (seasons)")
    ap.add_argument("--cache", action="store_true", help="reuse --cache-path instead of reloading the DB")
    ap.add_argument("--cache-path", default="/scratch/props_data.pkl")
    ap.add_argument("--rate-half-life", type=lambda v: None if v.lower() == "none" else float(v), default=F.SKATER_RATE_HALFLIFE_DAYS,
                    help="calendar half-life (days) of the shrunk per-60 rates (default: production setting)")
    ap.add_argument("--ratings-half-life", type=lambda v: None if v.lower() == "none" else float(v), default=F.RATING_HALFLIFE_DAYS,
                    help="calendar half-life (days) in skater_ratings (teammate quality)")
    ap.add_argument("--ratings-age", default=F.RATING_AGE_MODE, type=lambda v: None if v.lower() == "none" else v,
                    help="skater_ratings age mode: aging or none (default: production setting)")
    args = ap.parse_args()
    import os
    if args.cache and os.path.exists(args.cache_path):
        skaters, goalies, team_stats, games, odds = pd.read_pickle(args.cache_path)
    else:
        skaters, goalies, team_stats, games, odds = asyncio.run(_load())
        if args.cache:
            pd.to_pickle((skaters, goalies, team_stats, games, odds), args.cache_path)
    tf = context(team_stats, games, goalies, odds)
    report = {}
    if args.goalies:
        g = F.goalie_features(goalies, tf)
        g = g[(g["toi"] == g.groupby(["game_id", "team"])["toi"].transform("max")) & (g["games_career"] >= 1)].copy()
        g["saves"] = g["sog"] - g["goals_against"]
        for t in ("goals_against", "sog", "saves"):
            g[f"trend_{t}"] = F.league_trend(g, t)
        base = F.GOALIE_FEATURE_COLUMNS
        variants = {"base_2008": (base, 2008), "+market_2008": (base + F.MARKET_CONTEXT, 2008),
                    "+market_2019": (base + F.MARKET_CONTEXT, 2019)}
        if args.variants:
            variants = {k: v for k, v in variants.items() if k in args.variants}
        last = list(variants)[-1]
        for h in args.half_lives:
            variants[f"{last}_hl{h:g}"] = (*variants[last][:2], h)
        out, preds = run(g, ["goals_against", "sog", "saves"], variants, GOALIE_POISSON_PARAMS, trend={"sog", "saves"})
        show(out, ["goals_against", "sog", "saves"])
        preds.to_pickle(args.preds_out or "/scratch/props_preds_goalie.pkl")
        report["goalies"] = out
    else:
        extra = tuple(c for c in ("shots_on_goal", "pp_toi", "pp_points", "hits", "blocked_shots")
                      if c in skaters and skaters[c].notna().any())
        lineups = F.played_lineups(skaters, F.skater_ratings(skaters, args.ratings_half_life, args.ratings_age))
        df, _ = F.skater_features(skaters, tf, extra_stats=extra, shares=F.skater_shares(skaters), lineups=lineups,
                                  rate_half_life_days=args.rate_half_life)
        df = df[df["games_career"] >= 1]
        base = F.SKATER_FEATURE_COLUMNS
        extra_cols = [f"{s}_{w}" for s in extra for w in ("l5", "ewm", "season", "career")]
        variants = {"base_2008": (base, 2008), "+market_2008": (base + F.MARKET_CONTEXT, 2008)}
        if extra:
            variants["+market+sog/pp_2008"] = (best := base + F.MARKET_CONTEXT + extra_cols, 2008)
            variants["+shares"] = (best + F.SKATER_SHARE_COLUMNS, 2008)
            variants["+teammates"] = (best + F.TEAMMATE_COLUMNS, 2008)
            variants["+shares+teammates"] = (best + F.SKATER_SHARE_COLUMNS + F.TEAMMATE_COLUMNS, 2008)
            variants["+shares+teammates+age"] = (best + F.SKATER_SHARE_COLUMNS + F.TEAMMATE_COLUMNS + F.SKATER_AGE_COLUMNS, 2008)
        targets = [t for t in args.targets if t in df and df[t].notna().any()]
        for t in args.skater_trend:
            df[f"trend_{t}"] = F.league_trend(df, t)
        if args.variants:
            variants = {k: v for k, v in variants.items() if k in args.variants}
        last = list(variants)[-1]
        for h in args.half_lives:
            variants[f"{last}_hl{h:g}"] = (*variants[last][:2], h)
        # keep only what the variants use, in float32, so the fold copies fit in memory
        used = list(dict.fromkeys(c for v in variants.values() for c in v[0]))
        meta = ["game_id", "player_id", "season", "team", "opponent", "date"] + targets + [f"trend_{t}" for t in args.skater_trend]
        df = pd.concat([df[meta], df[used].astype(np.float32)], axis=1)
        del skaters, lineups
        out, preds = run(df, targets, variants, POISSON_PARAMS, trend=set(args.skater_trend))
        show(out, targets)
        keep = ["game_id", "player_id", "season", "team", "opponent", "date"] + targets + [c for c in preds if c.startswith("pred_")]
        preds[keep].to_pickle(args.preds_out or ("/scratch/props_preds_skater_trend.pkl" if args.skater_trend else "/scratch/props_preds_skater.pkl"))
        report["skaters"] = out
    path = "/scratch/props_models_goalie.json" if args.goalies else "/scratch/props_models_skater.json"
    if args.preds_out:
        path = args.preds_out.rsplit(".", 1)[0] + ".json"
    with open(path, "w") as f:
        json.dump(report, f, indent=1, default=float)
