"""How much does the expected lineup miss, and what would an injury report buy? (RESULTS_v5 section 2)

    python -m predictions.experiments.injury_eval --out /app/_scratch_inj

ESPN keeps no injury history, so the injury report itself can't be backtested. Instead:
1. Audit the production expected lineup (the previous game's 18 skaters, `features.rated_lineups`) against who
   actually played, 2022-23 to 2025-26 regular seasons: how often an expected skater sits, for how many games, and how
   much of the roster rating he carried.
2. Score the team model per game (rolling origin, as frames.evaluate) and compare it with the closing line on games
   that start a regular's absence (the roster rating still counts him) against other games.
3. Proxy backtest: drop absences that a pre-game report would plausibly have listed (expected skater who then misses
   2+ straight games; regulars only in the conservative variant) from the expected lineup with the live code
   (`features.drop_listed_out`), filling from the team's recent extras, and re-score with the model trained on
   production (previous-game) lineups, which is how the live change runs.
"""
import argparse
import asyncio
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss

from app.database import AsyncSessionLocal, engine
from predictions import features as F
from predictions.data import load_skater_logs, load_team_stats
from predictions.experiments.frames import TEST_SEASONS, build
from predictions.train import _team_logistic

ROSTER_COLS = ["roster_game_score", "roster_points", "roster_xg_pct", "roster_n"]
POOL_GAMES = 10             # extras: skaters who played for the team in its previous 10 games
REGULAR_F, REGULAR_D = 9, 4  # "regular": top-9 forward / top-4 defenceman by expected ice time in the expected lineup


async def _load():
    async with AsyncSessionLocal() as db:
        return await load_skater_logs(db), await load_team_stats(db)


def team_game_index(team_games: pd.DataFrame) -> pd.DataFrame:
    """(game_id, team, season, date, k): k = the team's game number within the season (0-based)."""
    tg = team_games[["game_id", "team", "season", "date"]].sort_values(["team", "date", "game_id"])
    return tg.assign(k=tg.groupby(["team", "season"]).cumcount())


def lineup_audit(skaters: pd.DataFrame, tg: pd.DataFrame, ratings: pd.DataFrame) -> pd.DataFrame:
    """One row per expected skater (rated lineup, top 18) per team-game: played, regular, games missed in a row
    from this one (absence; NaN when he played; season games left + 1000 when he never came back that season)."""
    lineups = F.rated_lineups(F.expected_lineups(skaters, tg), ratings)
    pos = skaters.drop_duplicates("player_id", keep="last").set_index("player_id")["position"]
    lu = lineups.merge(tg[["game_id", "team", "season", "k", "date"]], on=["game_id", "team"])
    lu["is_d"] = lu["player_id"].map(pos).eq("D")
    rank = lu.groupby(["game_id", "team", "is_d"])["exp_toi"].rank(ascending=False, method="first")
    lu["regular"] = np.where(lu["is_d"], rank <= REGULAR_D, rank <= REGULAR_F)
    played = pd.MultiIndex.from_frame(skaters[["game_id", "player_id"]])
    lu["played"] = pd.MultiIndex.from_frame(lu[["game_id", "player_id"]]).isin(played)
    # next game he plays for the same team that season
    apps = skaters[["game_id", "team", "player_id"]].merge(tg[["game_id", "team", "season", "k"]], on=["game_id", "team"])
    apps = apps.rename(columns={"k": "k_next"}).sort_values("k_next")
    miss = lu[~lu["played"]].sort_values("k")
    miss = pd.merge_asof(miss, apps[["team", "season", "player_id", "k_next"]].assign(k_key=apps["k_next"]),
                         left_on="k", right_on="k_key", by=["team", "season", "player_id"], direction="forward")
    n_games = tg.groupby(["team", "season"])["k"].max().rename("k_last")
    miss = miss.join(n_games, on=["team", "season"])
    miss["absence"] = (miss["k_next"] - miss["k"]).fillna(miss["k_last"] - miss["k"] + 1001)
    return lu.merge(miss[["game_id", "player_id", "absence"]], on=["game_id", "player_id"], how="left")


def recent_extras(skaters: pd.DataFrame, tg: pd.DataFrame, ratings: pd.DataFrame, games: pd.Series) -> pd.DataFrame:
    """Replacement candidates per team-game in `games`: skaters who played for the team in its previous POOL_GAMES
    games that season, with their pre-game expected ice time (game_id, team, player_id, position, exp_toi)."""
    apps = skaters[["game_id", "team", "player_id", "position"]].merge(tg, on=["game_id", "team"])
    want = tg[tg["game_id"].isin(games)]
    pools = []
    for lag in range(1, POOL_GAMES + 1):
        p = apps[["team", "season", "k", "player_id", "position"]].assign(k=apps["k"] + lag)
        pools.append(want.merge(p, on=["team", "season", "k"]))
    pool = pd.concat(pools).drop_duplicates(["game_id", "team", "player_id"])
    pool = pd.merge_asof(pool.sort_values("date"), ratings[["player_id", "date", "exp_toi"]], on="date", by="player_id",
                         allow_exact_matches=False)
    return pool[["game_id", "team", "player_id", "position", "exp_toi"]]


def roster_variant(skaters, tg, ratings, out_pairs: pd.DataFrame | None, fill: bool) -> pd.DataFrame:
    lineups = F.expected_lineups(skaters, tg)
    if out_pairs is not None:
        pos = skaters.drop_duplicates("player_id", keep="last").set_index("player_id")["position"]
        cands = recent_extras(skaters, tg, ratings, out_pairs["game_id"].unique()) if fill else None
        lineups = F.drop_listed_out(lineups, out_pairs, pos, cands)
    return F.roster_ratings(lineups, ratings)


def swap_roster(frame: pd.DataFrame, roster: pd.DataFrame) -> pd.DataFrame:
    """The team-model frame with its home/away/diff roster columns rebuilt from `roster`."""
    out = frame.drop(columns=[f"{s}_{c}" for s in ("home", "away", "diff") for c in ROSTER_COLS], errors="ignore")
    for side in ("home", "away"):
        r = roster.rename(columns={c: f"{side}_{c}" for c in ROSTER_COLS}).rename(columns={"team": f"{side}_team_tri_code"})
        out = out.merge(r, on=["game_id", f"{side}_team_tri_code"], how="left")
    for c in ROSTER_COLS[:3]:
        out[f"diff_{c}"] = out[f"home_{c}"] - out[f"away_{c}"]
    return out


def rolling_preds(train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> pd.Series:
    """P(home win) for each regular-season test-season game, from a model fit on `train` rows of earlier seasons
    (all seasons before the previous one, as frames.evaluate)."""
    out = []
    for season in TEST_SEASONS:
        tr = train[train["season"] < season - 1]
        te = test[(test["season"] == season) & (test["is_playoff"] == 0)]
        model = _team_logistic().fit(tr[cols], tr["home_win"].astype(int))
        out.append(pd.Series(model.predict_proba(te[cols])[:, 1], index=pd.Index(te["game_id"].to_numpy(), name="game_id")))
    return pd.concat(out)


def ll(y, p) -> float:
    return float(log_loss(y, p, labels=[0, 1]))


def mean_by_season(frame: pd.DataFrame, p: pd.Series) -> tuple[float, dict]:
    f = frame.set_index("game_id").loc[p.index]
    per = {s: ll(f.loc[f["season"] == s, "home_win"], p[(f["season"] == s).to_numpy()]) for s in TEST_SEASONS}
    return float(np.mean(list(per.values()))), per


def main(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    frame_path = out_dir / "team_frame.pkl"
    frame = pd.read_pickle(frame_path) if frame_path.exists() else build()
    frame.to_pickle(frame_path)
    engine.sync_engine.dispose(close=False)   # build() ran its own event loop; don't reuse its pooled connections
    skaters, team_stats = asyncio.run(_load())
    tg = team_game_index(F.build_team_games(team_stats))
    ratings = F.skater_ratings(skaters)
    test = frame[frame["season"].isin(TEST_SEASONS) & (frame["is_playoff"] == 0)]

    # ---- 1. lineup audit ----
    audit = lineup_audit(skaters, tg[tg["season"] >= min(TEST_SEASONS)], ratings)
    audit = audit[audit["game_id"].isin(test["game_id"])]
    audit.to_pickle(out_dir / "audit.pkl")
    audit = audit.assign(missed=~audit["played"], missed_regular=~audit["played"] & audit["regular"],
                         missed_rating=audit["exp_game_score"].where(~audit["played"], 0.0))
    tg_n = audit.groupby(["game_id", "team"]).agg(missing=("missed", "sum"), missing_regular=("missed_regular", "sum"),
                                                  rating=("exp_game_score", "sum"), missing_rating=("missed_rating", "sum"))
    miss = audit[audit["missed"]]
    print(f"== 1. expected lineup vs who played, {len(tg_n)} team-games (regular season {TEST_SEASONS[0]}-{TEST_SEASONS[-1] + 1})")
    print(f"expected skaters who didn't play: {(~audit['played']).mean():.2%} of expected-lineup slots, "
          f"{tg_n['missing'].mean():.2f} per team-game; team-games with >=1: {(tg_n['missing'] > 0).mean():.1%}, "
          f"with a regular missing: {(tg_n['missing_regular'] > 0).mean():.1%}")
    print(f"share of expected roster game score that didn't play: {(tg_n['missing_rating'].sum() / tg_n['rating'].sum()):.2%}")
    bins = pd.cut(miss["absence"], [0, 1, 2, 4, 9, 1000, np.inf], labels=["1", "2", "3-4", "5-9", "10+", "rest of season"])
    table = pd.DataFrame({"all": bins.value_counts(normalize=True), "regulars": bins[miss["regular"]].value_counts(normalize=True)})
    print("length of the absence each miss starts (games in a row):\n" + table.sort_index().round(3).to_string())
    print(f"misses by regulars: {miss['regular'].mean():.1%}; regulars' share of the missing rating: "
          f"{miss.loc[miss['regular'], 'exp_game_score'].sum() / miss['exp_game_score'].sum():.1%}")
    returning = skaters[skaters["game_id"].isin(test["game_id"])].merge(
        audit[["game_id", "player_id"]].assign(exp=1), on=["game_id", "player_id"], how="left")
    print(f"skaters who played but weren't in the expected lineup (returns, call-ups): "
          f"{returning['exp'].isna().groupby([returning['game_id'], returning['team']]).sum().mean():.2f} per team-game")

    # ---- 2. model vs market where the lineup is stale ----
    cols = F.TEAM_FEATURE_COLUMNS
    p = rolling_preds(frame, frame, cols)
    g = test.set_index("game_id").loc[p.index].assign(p=p)
    reg = tg_n["missing_regular"].reset_index()
    for side in ("home", "away"):
        side_reg = reg.rename(columns={"team": f"{side}_team_tri_code", "missing_regular": f"{side}_mr"})
        g = g.reset_index().merge(side_reg, on=["game_id", f"{side}_team_tri_code"], how="left").set_index("game_id")
    g["first_game_miss"] = (g["home_mr"].fillna(0) + g["away_mr"].fillna(0)) > 0
    print("\n== 2. team model vs closing line, games starting a regular's absence vs the rest")
    for name, sub in (("all", g), ("a regular's absence starts", g[g["first_game_miss"]]), ("no new absence", g[~g["first_game_miss"]])):
        m = sub[sub["mkt"].notna()]
        print(f"{name:<28} n={len(sub):5d}  model {ll(sub['home_win'], sub['p']):.4f}   on market games: model "
              f"{ll(m['home_win'], m['p']):.4f} vs close {ll(m['home_win'], m['mkt']):.4f} "
              f"(gap {ll(m['home_win'], m['p']) - ll(m['home_win'], m['mkt']):+.4f})")
    g.to_pickle(out_dir / "per_game.pkl")

    # ---- 3. proxy backtest ----
    lu_miss = audit[~audit["played"]]
    variants = {
        "previous-game lineup (production)": (None, False),
        "drop regulars out 2+ games, fill": (lu_miss[lu_miss["regular"] & (lu_miss["absence"] >= 2)], True),
        "drop regulars out 2+ games, no fill": (lu_miss[lu_miss["regular"] & (lu_miss["absence"] >= 2)], False),
        "drop anyone out 2+ games, fill": (lu_miss[lu_miss["absence"] >= 2], True),
        "drop every miss, fill (all lineup news)": (lu_miss, True),
    }
    print("\n== 3. proxy backtest (model trained on production lineups; test-season roster rating rebuilt)")
    base_mean, _ = mean_by_season(frame, p)
    for name, (pairs, fill) in variants.items():
        if pairs is None:
            q = p
        else:
            roster = roster_variant(skaters, tg[tg["season"] >= min(TEST_SEASONS)], ratings,
                                    pairs[["game_id", "player_id"]], fill)
            swapped = swap_roster(frame[frame["season"].isin(TEST_SEASONS)], roster)
            q = rolling_preds(frame, swapped, cols)
        mean, per = mean_by_season(frame, q)
        sub = g.loc[q.index]
        first = sub["first_game_miss"].to_numpy()
        n_changed = 0 if pairs is None else pairs["game_id"].nunique()
        print(f"{name:<40} " + " ".join(f"{s}:{per[s]:.4f}" for s in TEST_SEASONS) + f"  mean {mean:.4f} "
              f"({mean - base_mean:+.4f}); games starting an absence: {ll(sub['home_win'][first], q[first]):.4f}; "
              f"games changed {n_changed}")
    # the ceiling: the actual lineup at test time
    actual = F.roster_ratings(skaters.assign(date=F._date(skaters["game_date"]))[["game_id", "team", "date", "player_id"]], ratings)
    q = rolling_preds(frame, swap_roster(frame[frame["season"].isin(TEST_SEASONS)], actual), cols)
    mean, per = mean_by_season(frame, q)
    print(f"{'actual lineup (ceiling)':<40} " + " ".join(f"{s}:{per[s]:.4f}" for s in TEST_SEASONS) + f"  mean {mean:.4f} ({mean - base_mean:+.4f})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/app/_scratch_inj")
    main(Path(ap.parse_args().out))
