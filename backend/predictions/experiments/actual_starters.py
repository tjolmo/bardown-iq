"""True starting goalies (NHL play-by-play first shot faced / boxscore starter flag, stored in game_starters by
`python -m app.backfill --actual-starters`) against the schedule projection and the most-ice-time "starter".

    python -m predictions.experiments.actual_starters [--skip team goalies skaters] [--cache]
        [--goalie-seeds 3 --full-params] | --team-extra

Starter sets (each gives starter_gsax60 for every team-game):
  proj_toi   the v4 projection: most starts in the last 10 games, counted from the goalie with the most ice time
  proj_true  the same projection, counted from true starters
  actual     the true starter (what an announced/confirmed starter approximates live)
The team model is trained on one set and scored on another, so "train actual / test actual" (starter known before the
game, as with ESPN confirmed starters) and "train actual / test proj_true" (starter not announced) are both reported.
Goalie models: rows filtered to the most-ice-time goalie (v4) or the true starter, scored on true-starter rows (how
saves props settle). Skater models: opposing starter quality from each set.
"""
import argparse
import asyncio
import json
import os
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, mean_poisson_deviance
from xgboost import XGBRegressor
from app.database import AsyncSessionLocal
from app.crud.game_starters import load_game_starters
from predictions import features as F
from predictions.config import GOALIE_POISSON_PARAMS, POISSON_PARAMS
from predictions.experiments.frames import _load as _load_frames, TEST_SEASONS
from predictions.train import _team_logistic

FAST = {"learning_rate": 0.05, "early_stopping_rounds": 60}   # relative comparisons only
CACHE = "/app/.scratch/actual_starters_data.pkl"
OUT = "/app/.scratch/actual_starters.json"

async def _load_all():
    frames = await _load_frames()
    async with AsyncSessionLocal() as db:
        return (*frames, await load_game_starters(db))

def load(cache: bool):
    if cache and os.path.exists(CACHE):
        return pd.read_pickle(CACHE)
    data = asyncio.run(_load_all())
    if cache:
        pd.to_pickle(data, CACHE)
    return data

def starter_sets(team_games, goalies, known) -> dict[str, pd.DataFrame]:
    """Starter picks (game_id, team, player_id, status) per starter set."""
    actual_only = F.true_starters(known).assign(status=F.ACTUAL_STATUS)
    picks = {"proj_toi": F.starter_picks(team_games, goalies),
             "proj_true": F.starter_picks(team_games, goalies, actual_only),
             "actual": F.starter_picks(team_games, goalies, actual_only, prefer_actual=True)}
    return picks

# ---------- coverage / agreement ----------

def coverage(games, goalies, known, picks) -> dict:
    g = games[(games["id"] // 10000 % 100).isin([2, 3]) & games["home_score"].notna()]
    true = F.true_starters(known)
    n_true = true.groupby("game_id").size()
    out = {}
    for season, grp in g.groupby("season"):
        both = (n_true.reindex(grp["id"]).fillna(0) >= 2).mean()
        out[int(season)] = {"games": len(grp), "both_starters": round(float(both), 4)}
    # how often the most-ice-time goalie / the projections name someone else than the true starter
    toi = F.most_ice_time(goalies).merge(true, on=["game_id", "team"], suffixes=("", "_true"))
    toi["season"] = toi["game_id"] // 1000000
    for season, grp in toi.groupby("season"):
        out.setdefault(int(season), {})["most_toi_wrong"] = round(float((grp["player_id"] != grp["player_id_true"]).mean()), 4)
    for name in ("proj_toi", "proj_true"):
        p = picks[name].merge(true, on=["game_id", "team"], suffixes=("", "_true")).dropna(subset=["player_id"])
        p["season"] = p["game_id"] // 1000000
        for season, grp in p.groupby("season"):
            out.setdefault(int(season), {})[f"{name}_right"] = round(float((grp["player_id"] == grp["player_id_true"]).mean()), 4)
    return out

# ---------- team model ----------

def team_frames(team_stats, games, goalies, skaters, odds, picks) -> dict[str, pd.DataFrame]:
    team_games = F.build_team_games(team_stats)
    roster = F.roster_ratings(F.expected_lineups(skaters, team_games), F.skater_ratings(skaters))
    team_feats = F.team_history_features(team_games)
    frames = {}
    for name, p in picks.items():
        frame = F.build_team_model_frame(games, team_feats, [F.starter_features(team_games, goalies, picks=p), roster])
        game_type = frame["game_id"] // 10000 % 100
        frame = frame[game_type.isin([2, 3]) & frame["home_win"].notna() & frame["home_games_season"].notna()]
        frame = frame.assign(is_playoff=(frame["game_id"] // 10000 % 100 == 3).astype(float))
        frames[name] = frame.merge(odds, on="game_id", how="left").sort_values("game_id").reset_index(drop=True)
    return frames

def evaluate_cross(train_frame, test_frame, cols=F.TEAM_FEATURE_COLUMNS, playoffs=False) -> dict:
    """frames.evaluate with the model fit on `train_frame` and scored on `test_frame`'s rows (same games)."""
    out = {}
    for test in TEST_SEASONS:
        tr = train_frame[train_frame["season"] < test - 1]
        te = test_frame[(test_frame["season"] == test) & ((test_frame["is_playoff"] == 1) == playoffs)]
        p = _team_logistic().fit(tr[cols], tr["home_win"].astype(int)).predict_proba(te[cols])[:, 1]
        m = te["mkt"].notna().to_numpy()
        out[test] = {"model": log_loss(te["home_win"], p, labels=[0, 1]),
                     "market": log_loss(te["home_win"][m], te["mkt"][m], labels=[0, 1]) if m.any() else np.nan}
    out["mean_model"] = float(np.mean([out[t]["model"] for t in TEST_SEASONS]))
    out["mean_market"] = float(np.nanmean([out[t]["market"] for t in TEST_SEASONS]))
    return out

def run_team(data, picks) -> dict:
    team_stats, games, goalies, skaters, odds, known = data
    frames = team_frames(team_stats, games, goalies, skaters, odds, picks)
    combos = [("proj_toi", "proj_toi"), ("proj_true", "proj_true"), ("proj_toi", "actual"), ("proj_true", "actual"),
              ("actual", "actual"), ("actual", "proj_true"), ("actual", "proj_toi")]
    out = {}
    for tr, te in combos:
        r = evaluate_cross(frames[tr], frames[te])
        po = evaluate_cross(frames[tr], frames[te], playoffs=True)
        out[f"train {tr} / test {te}"] = {"regular": r, "playoffs_mean": po["mean_model"], "playoffs_market": po["mean_market"]}
        print(f"team  train {tr:<9s} test {te:<9s} " + " ".join(f"{t}:{r[t]['model']:.4f}" for t in TEST_SEASONS)
              + f"  mean {r['mean_model']:.4f} (market {r['mean_market']:.4f})  playoffs {po['mean_model']:.4f} "
              f"(market {po['mean_market']:.4f})", flush=True)
    return out

def run_team_extra(data, picks) -> dict:
    """Features only a known starter makes possible, trained and scored with actual starters (starter announced)
    and scored with the projection too (not announced: then every flag is 0 and the quality is the projected one's):
    backup = the starter isn't the projected one; share = the starter's share of the team's last 10 starts;
    gsax60 with a lighter (10 h) or heavier (50 h) prior."""
    team_stats, games, goalies, skaters, odds, known = data
    team_games = F.build_team_games(team_stats)
    roster = F.roster_ratings(F.expected_lineups(skaters, team_games), F.skater_ratings(skaters))
    team_feats = F.team_history_features(team_games)
    hist = F.actual_starters(goalies, known).merge(team_games[["game_id", "team", "date"]], on=["game_id", "team"])
    hist = hist.sort_values(["team", "date", "game_id"])
    proj = picks["proj_true"][["game_id", "team", "player_id"]].rename(columns={"player_id": "proj_id"})

    def extra(p):
        e = p[["game_id", "team", "player_id"]].merge(proj, on=["game_id", "team"], how="left")
        e["starter_backup"] = (e["player_id"] != e["proj_id"]).astype(float)
        # share of the team's previous 10 starts made by this goalie
        shares = []
        for team, grp in hist.groupby("team", sort=False):
            ids = grp["player_id"].to_list()
            for i, gid in enumerate(grp["game_id"]):
                shares.append((gid, team, pd.Series(ids[max(0, i - 10):i]).value_counts(normalize=True).to_dict()))
        sh = pd.DataFrame(shares, columns=["game_id", "team", "_shares"])
        e = e.merge(sh, on=["game_id", "team"], how="left")
        e["starter_share"] = [d.get(pid, 0.0) if isinstance(d, dict) else np.nan for d, pid in zip(e["_shares"], e["player_id"])]
        out = e[["game_id", "team", "starter_backup", "starter_share"]]
        for hours in (10.0, 50.0):
            prior, F.GOALIE_PRIOR_HOURS = F.GOALIE_PRIOR_HOURS, hours
            try:
                q = F.starter_features(team_games, goalies, picks=p).rename(columns={"starter_gsax60": f"starter_gsax60_p{hours:g}"})
            finally:
                F.GOALIE_PRIOR_HOURS = prior
            out = out.merge(q, on=["game_id", "team"], how="left")
        return out

    frames = {}
    for name in ("actual", "proj_true"):
        p = picks[name]
        side = [F.starter_features(team_games, goalies, picks=p), roster, extra(p)]
        frame = F.build_team_model_frame(games, team_feats, side)
        for c in ("starter_backup", "starter_share", "starter_gsax60_p10", "starter_gsax60_p50"):
            frame[f"diff_{c}"] = frame[f"home_{c}"] - frame[f"away_{c}"]
        game_type = frame["game_id"] // 10000 % 100
        frame = frame[game_type.isin([2, 3]) & frame["home_win"].notna() & frame["home_games_season"].notna()]
        frame = frame.assign(is_playoff=(frame["game_id"] // 10000 % 100 == 3).astype(float))
        frames[name] = frame.merge(odds, on="game_id", how="left").sort_values("game_id").reset_index(drop=True)
    base = F.TEAM_FEATURE_COLUMNS
    swap = lambda old, new: [new if c == old else c for c in base]
    variants = {"base": base, "+backup": base + ["diff_starter_backup"], "+share": base + ["diff_starter_share"],
                "+backup+share": base + ["diff_starter_backup", "diff_starter_share"],
                "gsax prior 10h": swap("diff_starter_gsax60", "diff_starter_gsax60_p10"),
                "gsax prior 50h": swap("diff_starter_gsax60", "diff_starter_gsax60_p50")}
    out = {}
    for name, cols in variants.items():
        for te in ("actual", "proj_true"):
            r = evaluate_cross(frames["actual"], frames[te], cols)
            out[f"{name} / test {te}"] = r
            print(f"team-extra {name:<16s} train actual test {te:<9s} " + " ".join(f"{t}:{r[t]['model']:.4f}" for t in TEST_SEASONS)
                  + f"  mean {r['mean_model']:.4f}", flush=True)
    return out

# ---------- goalie models ----------

GOALIE_TARGETS = ["goals_against", "sog", "saves"]

def _context(team_stats, games, goalies, picks_one, odds):
    team_games = F.build_team_games(team_stats)
    tf = F.team_history_features(team_games)
    tf = tf.merge(F.implied_team_goals(games, odds.rename(columns={"mkt": "home_prob_novig"})), on=["game_id", "team"], how="left")
    st = F.starter_features(team_games, goalies, picks=picks_one).rename(columns={"starter_gsax60": "team_starter_gsax60"})
    return tf.merge(st, on=["game_id", "team"], how="left")

def _fit_predict(tr, va, te_sets: dict, cols, target, params, margin, fast=True):
    bm = (lambda d: np.log(d[f"trend_{target}"].to_numpy())) if margin else (lambda d: None)
    m = XGBRegressor(**(params | FAST if fast else params))
    m.fit(tr[cols].astype(np.float32), tr[target], base_margin=bm(tr), eval_set=[(va[cols].astype(np.float32), va[target])],
          base_margin_eval_set=[bm(va)] if margin else None, verbose=False)
    return {k: m.predict(te[cols].astype(np.float32), base_margin=bm(te)) for k, te in te_sets.items()}

def _dev(y, mu):
    return float(mean_poisson_deviance(y, np.clip(mu, 1e-6, None)))

def run_goalies(data, picks, seeds=(42,), fast=True) -> dict:
    """Goalie models: training rows = most-ice-time goalie (v4) or true starter; opposing-starter context from the
    projection (v4) or the true starter. Scored on true-starter test rows (with the context of each test mode) and,
    for reference, on most-ice-time rows (v4's own evaluation set). As in production, a model's league-trend margin
    comes from the kind of rows it was trained on."""
    team_stats, games, goalies, skaters, odds, known = data
    actual_only = F.true_starters(known).assign(status=F.ACTUAL_STATUS)
    has_true = pd.MultiIndex.from_frame(F.true_starters(known)[["game_id", "team"]])
    feats = {}
    for ctx in ("proj_toi", "actual"):
        g = F.goalie_features(goalies, _context(team_stats, games, goalies, picks[ctx], odds))
        g["saves"] = g["sog"] - g["goals_against"]
        g["is_true"] = F.starter_rows(g, actual_only)
        g["is_toi"] = g["toi"] == g.groupby(["game_id", "team"])["toi"].transform("max")
        g["has_true"] = g.set_index(["game_id", "team"]).index.isin(has_true)
        for rows in ("is_true", "is_toi"):
            for t in ("sog", "saves"):
                g.loc[g[rows], f"trend_{rows}_{t}"] = F.league_trend(g[g[rows]], t)
        feats[ctx] = g[g["games_career"] >= 1].reset_index(drop=True)
    cols = F.GOALIE_FEATURE_COLUMNS + F.MARKET_CONTEXT
    variants = {"v4: rows most-TOI, ctx proj": ("is_toi", "proj_toi"), "rows true, ctx proj": ("is_true", "proj_toi"),
                "rows true, ctx actual": ("is_true", "actual")}
    tests = {"true rows, ctx proj": ("proj_toi", "is_true"), "true rows, ctx actual": ("actual", "is_true"),
             "most-TOI rows, ctx proj": ("proj_toi", "is_toi")}
    out = {}
    for name, (rows, ctx) in variants.items():
        res = {}
        for t in GOALIE_TARGETS:
            margin = t in ("sog", "saves")
            def frame(src, mask):
                d = src[mask].copy()
                if margin:
                    d[f"trend_{t}"] = d[f"trend_{rows}_{t}"]   # the training population's league level
                    d = d[d[f"trend_{t}"].notna()]
                return d
            train_rows = frame(feats[ctx], feats[ctx][rows])
            for test in TEST_SEASONS:
                tr = train_rows[train_rows["season"] < test - 1]
                va = train_rows[train_rows["season"] == test - 1]
                te_sets = {}
                for k, (tctx, trows) in tests.items():
                    src = feats[tctx]
                    mask = (src["season"] == test) & src[trows] & (src["has_true"] if trows == "is_true" else True)
                    if margin:   # the training population's trend on the test rows' dates
                        lvl = feats[ctx][feats[ctx][rows]].groupby("date")[f"trend_{rows}_{t}"].first()
                        src = src.assign(**{f"trend_{rows}_{t}": src["date"].map(lvl)})
                    te_sets[k] = frame(src, mask)
                # several seeds (subsampling) averaged, since the differences are close to the run-to-run noise
                preds = [_fit_predict(tr, va, te_sets, cols, t, GOALIE_POISSON_PARAMS | {"random_state": seed}, margin, fast)
                         for seed in seeds]
                for k in te_sets:
                    mu, y = np.mean([p[k] for p in preds], axis=0), te_sets[k][t].to_numpy()
                    res.setdefault(k, {}).setdefault(t, {})[test] = _dev(y, mu)
                    res[k].setdefault(f"{t}_bias", {})[test] = float(mu.mean() - y.mean())
        out[name] = res
        for k, r in res.items():
            print(f"goalie {name:<30s} | {k:<24s} " + "  ".join(
                f"{t}: {np.mean(list(r[t].values())):.4f} (" + " ".join(f"{v:.4f}" for v in r[t].values())
                + f"; bias {np.mean(list(r[t + '_bias'].values())):+.3f})" for t in GOALIE_TARGETS), flush=True)
    return out

# ---------- skater models ----------

SKATER_TARGETS = ["goals", "shots_on_goal", "points"]

def run_skaters(data, picks) -> dict:
    """Skater models with the opposing starter's quality (opp_starter_gsax60) from the projection or the true
    starter, trained on one and scored on both. Test seasons 2024 and 2025 (as props_models)."""
    team_stats, games, goalies, skaters, odds, known = data
    extra = tuple(c for c in ("shots_on_goal", "pp_toi", "pp_points", "hits", "blocked_shots")
                  if c in skaters and skaters[c].notna().any())
    skaters = skaters.astype({c: np.float32 for c in skaters.select_dtypes("number").columns
                              if c not in ("game_id", "player_id", "season", "game_date")})
    lineups = F.played_lineups(skaters, F.skater_ratings(skaters))
    shares = F.skater_shares(skaters)
    cols = (F.SKATER_FEATURE_COLUMNS + F.MARKET_CONTEXT + [f"{s}_{w}" for s in extra for w in ("l5", "ewm", "season", "career")]
            + F.SKATER_SHARE_COLUMNS + F.TEAMMATE_COLUMNS)
    # features built once (projected context); the opposing starter's quality is swapped per starter set
    df, _ = F.skater_features(skaters, _context(team_stats, games, goalies, picks["proj_toi"], odds), extra_stats=extra,
                              shares=shares, lineups=lineups)
    df = df[df["games_career"] >= 1]
    meta = ["game_id", "player_id", "opponent", "season", "date"] + SKATER_TARGETS
    base = pd.concat([df[meta], df[cols].astype(np.float32)], axis=1).reset_index(drop=True)
    del df, lineups, shares
    team_games = F.build_team_games(team_stats)
    opp = {}
    for ctx in ("proj_toi", "actual"):
        st = F.starter_features(team_games, goalies, picks=picks[ctx]).rename(columns={"team": "opponent"})
        opp[ctx] = base[["game_id", "opponent"]].merge(st, on=["game_id", "opponent"], how="left")["starter_gsax60"].astype(np.float32).to_numpy()
    assert np.allclose(np.nan_to_num(opp["proj_toi"], nan=-9), np.nan_to_num(base["opp_starter_gsax60"].to_numpy(), nan=-9), atol=1e-5)
    base["trend_shots_on_goal"] = F.league_trend(base, "shots_on_goal")
    out = {}
    for test in (2024, 2025):
        tr_mask, va_mask, te_mask = (base["season"] < test - 1).to_numpy(), (base["season"] == test - 1).to_numpy(), (base["season"] == test).to_numpy()
        for train_ctx in ("proj_toi", "actual"):
            for t in SKATER_TARGETS:
                margin = t == "shots_on_goal"
                d = base.assign(opp_starter_gsax60=opp[train_ctx])
                ok = d[t].notna().to_numpy()
                tr, va = d[tr_mask & ok], d[va_mask & ok]
                te_sets = {k: base[te_mask & ok].assign(opp_starter_gsax60=opp[k][te_mask & ok]) for k in ("proj_toi", "actual")}
                preds = _fit_predict(tr, va, te_sets, cols, t, POISSON_PARAMS, margin)
                for k, mu in preds.items():
                    out.setdefault(f"train {train_ctx} / test {k}", {}).setdefault(t, {})[test] = _dev(te_sets[k][t].to_numpy(), mu)
                print(f"skater {test} train {train_ctx:<8s} {t:<14s} " + "  ".join(
                    f"test {k}: {out[f'train {train_ctx} / test {k}'][t][test]:.4f}" for k in preds), flush=True)
    return out

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip", nargs="*", default=[], choices=["team", "goalies", "skaters"])
    ap.add_argument("--goalie-seeds", type=int, default=1, help="average goalie predictions over this many seeds")
    ap.add_argument("--full-params", action="store_true", help="goalie models with the production learning rate / early stopping")
    ap.add_argument("--team-extra", action="store_true", help="only the extra known-starter team features")
    ap.add_argument("--cache", action="store_true", help=f"reuse / write {CACHE} instead of reloading the DB")
    args = ap.parse_args()
    data = load(args.cache)
    team_stats, games, goalies, skaters, odds, known = data
    picks = starter_sets(F.build_team_games(team_stats), goalies, known)
    report = {"coverage": coverage(games, goalies, known, picks)}
    for season, c in sorted(report["coverage"].items()):
        print("coverage", season, c, flush=True)
    if args.team_extra:
        with open(OUT.replace(".json", "_team_extra.json"), "w") as f:
            json.dump(run_team_extra(data, picks), f, indent=1, default=float)
        raise SystemExit(0)
    if "team" not in args.skip:
        report["team"] = run_team(data, picks)
    if "goalies" not in args.skip:
        report["goalies"] = run_goalies(data, picks, seeds=tuple(range(42, 42 + args.goalie_seeds)), fast=not args.full_params)
    if "skaters" not in args.skip:
        report["skaters"] = run_skaters(data, picks)
    out = OUT if not args.skip else OUT.replace(".json", "_" + "_".join(sorted({"team", "goalies", "skaters"} - set(args.skip))) + ".json")
    with open(out, "w") as f:
        json.dump(report, f, indent=1, default=float)
