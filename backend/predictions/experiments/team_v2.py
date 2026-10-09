"""Team win model experiments: more seasons (#1), richer team strength (#2), starting goalie (#4).

Team stats come from MoneyPuck's all_teams.csv (every game since 2008-09, split by situation) and starters from the
goalie season files. Labels come from final scores in a CSV export of the `games` table. Each feature group is added
on top of the previous ones and scored out of time on two folds.
    python -m predictions.experiments.team_v2 --data /scratch --train-start 2008
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from predictions import features as F

FOLDS = {"test_2025": (2024, 2025), "test_2024": (2023, 2024), "test_2023": (2022, 2023), "test_2022": (2021, 2022)}   # (early-stopping season, test season)
TRICODES = {"T.B": "TBL", "S.J": "SJS", "N.J": "NJD", "L.A": "LAK"}

# ---------- team stats by situation ----------

SITUATION_COLS = {
    "all": {"goalsFor": "gf", "goalsAgainst": "ga", "xGoalsFor": "xgf", "xGoalsAgainst": "xga",
            "shotAttemptsFor": "saf", "shotAttemptsAgainst": "saa"},
    "5on5": {"flurryScoreVenueAdjustedxGoalsFor": "xgf5", "flurryScoreVenueAdjustedxGoalsAgainst": "xga5",
             "scoreAdjustedShotsAttemptsFor": "cf5", "scoreAdjustedShotsAttemptsAgainst": "ca5",
             "goalsFor": "gf5", "goalsAgainst": "ga5"},
    "5on4": {"xGoalsFor": "pp_xgf", "goalsFor": "pp_gf", "iceTime": "pp_toi"},
    "4on5": {"xGoalsAgainst": "pk_xga", "goalsAgainst": "pk_ga", "iceTime": "pk_toi"},
}

def load_team_games(data: Path) -> pd.DataFrame:
    raw = pd.read_csv(data / "all_teams.csv")
    raw["team"] = raw["team"].replace(TRICODES)
    raw["opposingTeam"] = raw["opposingTeam"].replace(TRICODES)
    keys = ["gameId", "team", "opposingTeam", "season", "gameDate", "home_or_away", "playoffGame"]
    wide = None
    for situation, cols in SITUATION_COLS.items():
        part = raw.loc[raw["situation"] == situation, keys + list(cols)].rename(columns=cols)
        wide = part if wide is None else wide.merge(part, on=keys, how="left")
    wide = wide.rename(columns={"gameId": "game_id", "opposingTeam": "opponent", "gameDate": "game_date"})
    wide["is_home"] = (wide["home_or_away"] == "HOME").astype(float)
    wide["date"] = pd.to_datetime(wide["game_date"].astype(str), format="%Y%m%d")
    return wide.drop(columns="home_or_away").sort_values(["team", "date", "game_id"]).reset_index(drop=True)

V2_STATS = ["gf", "ga", "xgf", "xga", "saf", "saa", "xgf5", "xga5", "cf5", "ca5", "gf5", "ga5",
            "pp_xgf", "pp_gf", "pp_toi", "pk_xga", "pk_ga", "pk_toi"]

def team_strength(tg: pd.DataFrame) -> pd.DataFrame:
    feats = F._prior_features(tg, "team", V2_STATS, prefix="t_")
    out = pd.DataFrame({"game_id": tg["game_id"], "team": tg["team"]})
    for w in ("ewm", "season"):
        g = lambda s: feats[f"t_{s}_{w}"]
        out[f"xg_pct_{w}"] = g("xgf") / (g("xgf") + g("xga"))
        out[f"g_pct_{w}"] = g("gf") / (g("gf") + g("ga"))
        out[f"gsax_{w}"] = g("xga") - g("ga")
        out[f"xgf_{w}"], out[f"xga_{w}"] = g("xgf"), g("xga")
        out[f"xg5_pct_{w}"] = g("xgf5") / (g("xgf5") + g("xga5"))
        out[f"cf5_pct_{w}"] = g("cf5") / (g("cf5") + g("ca5"))
        out[f"g5_pct_{w}"] = g("gf5") / (g("gf5") + g("ga5"))
        out[f"pp_xgf60_{w}"] = g("pp_xgf") / g("pp_toi") * 3600
        out[f"pk_xga60_{w}"] = g("pk_xga") / g("pk_toi") * 3600
        out[f"pp_toi_{w}"], out[f"pk_toi_{w}"] = g("pp_toi") / 60, g("pk_toi") / 60   # penalties drawn / taken
    out["games_season"] = feats["t_games_season"]
    out["rest_days"] = F._rest_days(tg, "team").values
    return out

def xg_elo(games: pd.DataFrame, xg_share: dict, k: float = 8.0, home_adv: float = 35.0, carry: float = 0.7,
           w: float = 0.5) -> pd.DataFrame:
    """Elo whose update target blends the result with the game's score-adjusted 5v5 xG share,
    so it reacts to how a team played, not only to the bounces."""
    g = games.sort_values(["date", "id"])
    ratings, season_of, rows = {}, {}, []
    for gid, season, home, away, hs, as_ in zip(g["id"], g["season"], g["home_team_tri_code"],
                                                g["away_team_tri_code"], g["home_score"], g["away_score"]):
        for t in (home, away):
            if t not in ratings:
                ratings[t], season_of[t] = 1500.0, season
            elif season_of[t] != season:
                ratings[t], season_of[t] = 1500.0 + carry * (ratings[t] - 1500.0), season
        rh, ra = ratings[home], ratings[away]
        rows.append((gid, rh, ra))
        if pd.isna(hs):
            continue
        p = 1.0 / (1.0 + 10 ** (-(rh + home_adv - ra) / 400.0))
        target = 1.0 if hs > as_ else 0.0
        if gid in xg_share and not np.isnan(xg_share[gid]):
            target = (1 - w) * target + w * xg_share[gid]
        delta = 2 * k * (target - p)
        ratings[home], ratings[away] = rh + delta, ra - delta
    return pd.DataFrame(rows, columns=["game_id", "home_xelo", "away_xelo"])

# ---------- starting goalies ----------

def load_goalies(data: Path) -> pd.DataFrame:
    frames = []
    for s in range(2008, 2027):
        p = data / f"goalies_{s}.pkl"
        if p.exists():
            g = pd.read_pickle(p)
            frames.append(g.loc[g["situation"] == "all", ["playerId", "gameId", "playerTeam", "gameDate", "season",
                                                          "icetime", "xGoals", "goals"]])
    g = pd.concat(frames).rename(columns={"playerId": "goalie", "gameId": "game_id", "playerTeam": "team",
                                          "gameDate": "game_date", "icetime": "toi", "xGoals": "xga", "goals": "ga"})
    g["team"] = g["team"].replace(TRICODES)
    g["date"] = pd.to_datetime(g["game_date"].astype(str), format="%Y%m%d")
    g["gsax"] = g["xga"] - g["ga"]
    return g.sort_values(["goalie", "date", "game_id"]).reset_index(drop=True)

GOALIE_PRIOR_HOURS = 25.0   # shrink a goalie's GSAx rate toward 0 (league average) with ~25 games of prior

def goalie_state(g: pd.DataFrame) -> pd.DataFrame:
    """Each goalie's quality *after* each appearance; looked up strictly before a game date it is pre-game."""
    by = g.groupby("goalie", sort=False)
    state = pd.DataFrame({"goalie": g["goalie"], "date": g["date"]})
    hours = by["toi"].cumsum() / 3600
    state["g_gsax60"] = by["gsax"].cumsum() / (hours + GOALIE_PRIOR_HOURS)
    state["g_gsax_ewm"] = by["gsax"].transform(lambda s: s.ewm(halflife=15).mean())
    state["g_games"] = by.cumcount() + 1
    return state.drop_duplicates(["goalie", "date"], keep="last")

def starters(g: pd.DataFrame) -> pd.DataFrame:
    s = g.loc[g["toi"] == g.groupby(["game_id", "team"])["toi"].transform("max")]
    return s.drop_duplicates(["game_id", "team"])[["game_id", "team", "goalie", "date"]]

def projected_starters(team_games: pd.DataFrame, actual: pd.DataFrame) -> pd.DataFrame:
    """Who a model would guess starts, from the schedule alone: the goalie with the most starts in the team's last
    10 games, except on the second night of a back-to-back, when it's the most-used other goalie."""
    tg = team_games[["game_id", "team", "date"]].merge(actual[["game_id", "team", "goalie"]], on=["game_id", "team"], how="left")
    tg = tg.sort_values(["team", "date", "game_id"])
    out = []
    for team, grp in tg.groupby("team", sort=False):
        history: list = []
        prev_date, prev_starter = None, None
        for gid, date, starter in zip(grp["game_id"], grp["date"], grp["goalie"]):
            counts = pd.Series(history[-10:]).value_counts() if history else pd.Series(dtype=int)
            pick = counts.index[0] if len(counts) else np.nan
            if prev_date is not None and (date - prev_date).days <= 1 and pick == prev_starter and len(counts) > 1:
                pick = counts.index[1]
            out.append((gid, team, pick))
            if not pd.isna(starter):
                history.append(starter)
            prev_date, prev_starter = date, starter
    return pd.DataFrame(out, columns=["game_id", "team", "goalie"])

def attach_goalie(frame: pd.DataFrame, picks: pd.DataFrame, state: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Joins each side's chosen goalie and his pre-game quality (state strictly before the game date)."""
    for side in ("home", "away"):
        p = picks.rename(columns={"team": f"{side}_team_tri_code", "goalie": f"{side}_{prefix}goalie"})
        frame = frame.merge(p, on=["game_id", f"{side}_team_tri_code"], how="left")
        left = frame[["game_id", "date_dt", f"{side}_{prefix}goalie"]].dropna().sort_values("date_dt")
        left[f"{side}_{prefix}goalie"] = left[f"{side}_{prefix}goalie"].astype("int64")
        right = state.rename(columns={"goalie": f"{side}_{prefix}goalie", "date": "date_dt"}).sort_values("date_dt")
        right = right.rename(columns={c: f"{side}_{prefix}{c}" for c in ("g_gsax60", "g_gsax_ewm", "g_games")})
        looked = pd.merge_asof(left, right, on="date_dt", by=f"{side}_{prefix}goalie", allow_exact_matches=False)
        frame = frame.merge(looked.drop(columns=["date_dt", f"{side}_{prefix}goalie"]), on="game_id", how="left")
    frame[f"diff_{prefix}gsax60"] = frame[f"home_{prefix}g_gsax60"] - frame[f"away_{prefix}g_gsax60"]
    return frame

# ---------- model frame ----------

def build_frame(data: Path, games: pd.DataFrame):
    tg = load_team_games(data)
    strength = team_strength(tg)
    xg_share = (tg[tg["is_home"] == 1].set_index("game_id").eval("xgf5 / (xgf5 + xga5)")).to_dict()

    frame = games.rename(columns={"id": "game_id"}).copy()
    frame = frame.merge(F.elo_ratings(games), on="game_id", how="left").merge(xg_elo(games, xg_share), on="game_id", how="left")
    for side in ("home", "away"):
        s = strength.rename(columns={c: f"{side}_{c}" for c in strength.columns if c not in ("game_id", "team")})
        frame = frame.merge(s.rename(columns={"team": f"{side}_team_tri_code"}), on=["game_id", f"{side}_team_tri_code"], how="left")
    frame["elo_diff"] = frame["home_elo"] + 35 - frame["away_elo"]
    frame["xelo_diff"] = frame["home_xelo"] + 35 - frame["away_xelo"]
    for c in ("xg_pct_ewm", "xg_pct_season", "g_pct_ewm", "gsax_ewm", "rest_days", "xg5_pct_ewm", "xg5_pct_season",
              "cf5_pct_season", "g5_pct_season", "pp_xgf60_season", "pk_xga60_season", "pp_toi_season", "pk_toi_season"):
        frame[f"diff_{c}"] = frame[f"home_{c}"] - frame[f"away_{c}"]
    frame["date_dt"] = pd.to_datetime(frame["date"].astype(str), format="%Y%m%d")

    goalies = load_goalies(data)
    state = goalie_state(goalies)
    actual = starters(goalies)
    projected = projected_starters(tg[tg["playoffGame"] == 0], actual)
    hit = projected.merge(actual, on=["game_id", "team"], suffixes=("_p", "_a"))
    accuracy = float((hit["goalie_p"] == hit["goalie_a"]).mean())
    frame = attach_goalie(frame, actual, state, "st_")
    frame = attach_goalie(frame, projected, state, "pj_")

    frame["home_win"] = (frame["home_score"] > frame["away_score"]).astype(float).where(frame["home_score"].notna())
    frame = frame[(frame["game_id"] // 10000 % 100 == 2) & frame["home_win"].notna() & frame["home_games_season"].notna()]
    return frame, accuracy

SIDE = lambda cols: [f"{s}_{c}" for s in ("home", "away") for c in cols]
BASE = (["home_elo", "away_elo", "elo_diff"]
        + SIDE(["xgf_ewm", "xga_ewm", "xg_pct_ewm", "xg_pct_season", "g_pct_ewm", "g_pct_season", "gsax_ewm",
                "gsax_season", "games_season", "rest_days"])
        + ["diff_xg_pct_ewm", "diff_xg_pct_season", "diff_g_pct_ewm", "diff_gsax_ewm", "diff_rest_days"])
EVEN = SIDE(["xg5_pct_ewm", "xg5_pct_season", "cf5_pct_season", "g5_pct_season"]) + [
    "diff_xg5_pct_ewm", "diff_xg5_pct_season", "diff_cf5_pct_season", "diff_g5_pct_season"]
SPECIAL = SIDE(["pp_xgf60_season", "pk_xga60_season", "pp_toi_season", "pk_toi_season"]) + [
    "diff_pp_xgf60_season", "diff_pk_xga60_season", "diff_pp_toi_season", "diff_pk_toi_season"]
XELO = ["home_xelo", "away_xelo", "xelo_diff"]
GOALIE = lambda p: SIDE([f"{p}g_gsax60", f"{p}g_gsax_ewm", f"{p}g_games"]) + [f"diff_{p}gsax60"]

LOGISTIC_BASE = ["elo_diff", "diff_xg_pct_ewm", "diff_xg_pct_season", "diff_g_pct_ewm", "diff_gsax_ewm", "diff_rest_days",
                 "home_rest_days", "away_rest_days"]
VARIANTS = {
    "base": (BASE, LOGISTIC_BASE),
    "+5v5_adjusted": (BASE + EVEN, LOGISTIC_BASE + ["diff_xg5_pct_season", "diff_xg5_pct_ewm"]),
    "+special_teams": (BASE + EVEN + SPECIAL, LOGISTIC_BASE + ["diff_xg5_pct_season", "diff_xg5_pct_ewm",
                                                               "diff_pp_xgf60_season", "diff_pk_xga60_season"]),
    "+xg_elo": (BASE + EVEN + SPECIAL + XELO, ["xelo_diff"] + LOGISTIC_BASE[1:] + ["diff_xg5_pct_season", "diff_xg5_pct_ewm",
                                                                                  "diff_pp_xgf60_season", "diff_pk_xga60_season"]),
}
L5 = LOGISTIC_BASE + ["diff_xg5_pct_season", "diff_xg5_pct_ewm"]
VARIANTS["5v5+projected_goalie"] = (BASE + EVEN + GOALIE("pj_"), L5 + ["diff_pj_gsax60"])
VARIANTS["5v5+actual_goalie"] = (BASE + EVEN + GOALIE("st_"), L5 + ["diff_st_gsax60"])
VARIANTS["5v5+projected_goalie+pp_pk"] = (BASE + EVEN + GOALIE("pj_"), L5 + ["diff_pj_gsax60", "diff_pp_xgf60_season", "diff_pk_xga60_season"])
VARIANTS["+projected_goalie"] = (VARIANTS["+xg_elo"][0] + GOALIE("pj_"), VARIANTS["+xg_elo"][1] + ["diff_pj_gsax60"])
VARIANTS["+actual_goalie (confirmed starter)"] = (VARIANTS["+xg_elo"][0] + GOALIE("st_"), VARIANTS["+xg_elo"][1] + ["diff_st_gsax60"])

XGB = dict(objective="binary:logistic", tree_method="hist", eval_metric="logloss", n_estimators=3000, learning_rate=0.01,
           max_depth=2, subsample=0.8, colsample_bytree=0.6, min_child_weight=30, reg_lambda=5.0, random_state=42,
           early_stopping_rounds=200)

def evaluate(frame, train_start, fold):
    valid_s, test_s = FOLDS[fold]
    tr = frame[(frame.season >= train_start) & (frame.season < valid_s)]
    va, te = frame[frame.season == valid_s], frame[frame.season == test_s]
    y = te["home_win"].astype(int).to_numpy()
    res = {"rows": {"train": len(tr), "valid": len(va), "test": len(te)},
           "home_rate": round(log_loss(y, np.full(len(y), tr.home_win.mean())), 4),
           "elo": round(log_loss(y, 1 / (1 + 10 ** (-te["elo_diff"] / 400))), 4)}
    for name, (cols, lcols) in VARIANTS.items():
        m = XGBClassifier(**XGB).fit(tr[cols].astype(np.float32), tr.home_win.astype(int),
                                     eval_set=[(va[cols].astype(np.float32), va.home_win.astype(int))], verbose=False)
        px = m.predict_proba(te[cols].astype(np.float32))[:, 1]
        lr = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(max_iter=2000))
        pl = lr.fit(tr[lcols], tr.home_win.astype(int)).predict_proba(te[lcols])[:, 1]
        p = (px + pl) / 2
        res[name] = {"blend": round(log_loss(y, p), 4), "xgb": round(log_loss(y, px), 4), "logistic": round(log_loss(y, pl), 4),
                     "auc": round(roc_auc_score(y, p), 4), "acc": round(float(np.mean((p > 0.5) == y)), 4)}
    return res

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/scratch")
    ap.add_argument("--games", default="/scratch/games.csv")
    ap.add_argument("--train-start", type=int, nargs="+", default=[2020])
    ap.add_argument("--out", default="/scratch/team_v2.json")
    args = ap.parse_args()
    games = pd.read_csv(args.games)
    games["season"] = games["season"] // 10000
    games.loc[~games["game_state"].isin(["OFF", "FINAL"]), ["home_score", "away_score"]] = np.nan
    frame, acc = build_frame(Path(args.data), games)
    report = {"projected_starter_accuracy": round(acc, 4)}
    print("projected starter accuracy", round(acc, 4), flush=True)
    for start in args.train_start:
        for fold in FOLDS:
            if start >= FOLDS[fold][0]:
                continue
            r = evaluate(frame, start, fold)
            report[f"train_from_{start}/{fold}"] = r
            print(f"train_from_{start}/{fold}", r["rows"], "home", r["home_rate"], "elo", r["elo"], flush=True)
            for k, v in r.items():
                if isinstance(v, dict) and "blend" in v:
                    print(f"   {k:<36s} {v}", flush=True)
    Path(args.out).write_text(json.dumps(report, indent=1))

if __name__ == "__main__":
    main()
