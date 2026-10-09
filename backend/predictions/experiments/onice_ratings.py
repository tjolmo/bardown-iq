"""Per-player on-ice ratings from MoneyPuck skater game logs, rolled up into per-team-game roster ratings.

    python -m predictions.experiments.onice_ratings            # build player-games cache, tune, write features, evaluate

Player rating (all state uses only games on dates strictly before the game being rated; it follows the player across
teams and seasons):
  * decayed sums: every per-game quantity x is accumulated as S(D) = sum_{games j, d_j < D} x_j * 0.5**((D - d_j)/H)
    (calendar-day half-life H, so injuries and offseasons decay naturally)
  * 5v5 on-ice, two flavours (per 60, shrunk toward 0 = league average with K seconds of pseudo-TOI):
      raw: (on-ice xGF - TOI * league 5v5 xG rate)          / (TOI + K)
      rel: (on-ice xGF - TOI * same-game off-ice xGF rate)  / (TOI + K)      (and the same for xGA)
  * PP: on-ice 5on4 xGF minus league 5on4 rate, shrunk with K_PP
  * individual: all-situation I_F_xGoals and gameScore minus the season's position-group (F/D) rate, shrunk with K_I
  * expected TOI by situation: decayed per-game mean (half-life H_TOI days) shrunk toward a position default with
    2 pseudo-games
Team roster rating = expected-TOI-weighted mean of the lineup's ratings (team on-ice xG rate is the TOI-weighted mean of
its skaters' on-ice rates). Lineups: `actual` = skaters who dressed; `prev` = skaters from the team's previous game that
season (first game of a season falls back to actual).
"""
import os
import numpy as np
import pandas as pd

SCRATCH = "/scratch"
SEASONS = range(2008, 2027)
TEAM_MAP = {"T.B": "TBL", "S.J": "SJS", "N.J": "NJD", "L.A": "LAK"}
EPOCH = pd.Timestamp("2008-09-01")
H_TOI = 40.0                       # days, expected-TOI half-life
TOI_DEFAULT = {"F": (12 * 60, 1.2 * 60, 15 * 60), "D": (17 * 60, 0.8 * 60, 20 * 60)}   # 5v5, 5on4, all (sec)
K_TOI = 2.0                        # pseudo-games of position-default TOI

# ---------------- player-game table ----------------

def _load_season(s: int) -> pd.DataFrame:
    raw = pd.read_pickle(f"{SCRATCH}/skaters_{s}.pkl")
    raw = raw[raw["gameId"] // 10000 % 100 == 2]
    key = ["playerId", "gameId"]
    base = raw[raw["situation"] == "all"][key + ["season", "playerTeam", "opposingTeam", "home_or_away", "gameDate",
                                                 "position", "icetime", "I_F_xGoals", "gameScore"]]
    base = base.rename(columns={"icetime": "tall", "I_F_xGoals": "ixg", "gameScore": "gs"})
    e = raw[raw["situation"] == "5on5"][key + ["icetime", "timeOnBench", "OnIce_F_xGoals", "OnIce_A_xGoals",
                                               "OffIce_F_xGoals", "OffIce_A_xGoals"]]
    e.columns = key + ["t5", "bench5", "onF5", "onA5", "offF5", "offA5"]
    p = raw[raw["situation"] == "5on4"][key + ["icetime", "OnIce_F_xGoals"]]
    p.columns = key + ["t4", "onF4"]
    df = base.merge(e, on=key, how="left").merge(p, on=key, how="left")
    num = ["t5", "bench5", "onF5", "onA5", "offF5", "offA5", "t4", "onF4"]
    df[num] = df[num].fillna(0.0)
    return df

def player_games() -> pd.DataFrame:
    path = f"{SCRATCH}/oi_player_games.pkl"
    if os.path.exists(path):
        return pd.read_pickle(path)
    df = pd.concat([_load_season(s) for s in SEASONS if os.path.exists(f"{SCRATCH}/skaters_{s}.pkl")],
                   ignore_index=True)
    df["team"] = df["playerTeam"].astype(str).replace(TEAM_MAP)
    df.loc[(df["team"] == "ARI") & (df["season"] <= 2013), "team"] = "PHX"
    df["pos"] = np.where(df["position"].astype(str) == "D", "D", "F")
    df["date"] = pd.to_datetime(df["gameDate"].astype(str), format="%Y%m%d")
    df["day"] = (df["date"] - EPOCH).dt.days.astype(float)
    df["home"] = (df["home_or_away"].astype(str) == "HOME").astype(int)
    df = df.rename(columns={"gameId": "game_id"}).drop(columns=["playerTeam", "opposingTeam", "home_or_away",
                                                                  "gameDate", "position"])
    df = df.drop_duplicates(["playerId", "game_id"])
    # team 5v5 time and same-game off-ice rates for the relative metric
    T5 = df.groupby(["game_id", "team"])["t5"].transform("sum") / 5.0
    off = (T5 - df["t5"]).clip(lower=0)
    ok = (off > 300) & (df["t5"] > 0)
    df["t5r"] = np.where(ok, df["t5"], 0.0)
    df["relF"] = np.where(ok, df["onF5"] - df["t5"] * df["offF5"] / off.where(ok, 1), 0.0)
    df["relA"] = np.where(ok, df["onA5"] - df["t5"] * df["offA5"] / off.where(ok, 1), 0.0)
    # deviations from league (season) rates; level constants cancel in home-away diffs
    g = df.groupby("season")
    L5 = g["onF5"].transform("sum") / g["t5"].transform("sum")
    L4 = g["onF4"].transform("sum") / g["t4"].transform("sum")
    df["rawF"] = df["onF5"] - df["t5"] * L5
    df["rawA"] = df["onA5"] - df["t5"] * L5
    df["ppd"] = df["onF4"] - df["t4"] * L4
    gp = df.groupby(["season", "pos"])
    df["ixd"] = df["ixg"] - df["tall"] * gp["ixg"].transform("sum") / gp["tall"].transform("sum")
    df["gsd"] = df["gs"] - df["tall"] * gp["gs"].transform("sum") / gp["tall"].transform("sum")
    df = df.sort_values(["playerId", "day", "game_id"]).reset_index(drop=True)
    df.to_pickle(path)
    return df

# ---------------- ratings ----------------

RATE_COLS = ["t5", "t5r", "relF", "relA", "rawF", "rawA", "t4", "ppd", "tall", "ixd", "gsd"]
TOI_COLS = ["one", "t5", "t4", "tall"]

def _cum(pg: pd.DataFrame, cols: list[str], H: float, tag: str) -> pd.DataFrame:
    w = np.power(2.0, pg["day"].to_numpy() / H)
    x = pg[cols].to_numpy() * w[:, None]
    c = pd.DataFrame(x, columns=[f"{tag}{c}" for c in cols]).groupby(pg["playerId"].to_numpy()).cumsum()
    return c

def lineups(pg: pd.DataFrame) -> dict[str, pd.DataFrame]:
    actual = pg[["game_id", "team", "home", "season", "day", "playerId", "pos"]].copy()
    tg = actual.drop_duplicates(["game_id", "team"]).sort_values(["team", "season", "day", "game_id"])
    tg["prev_gid"] = tg.groupby(["team", "season"])["game_id"].shift()
    tg["prev_gid"] = tg["prev_gid"].fillna(tg["game_id"]).astype(int)
    prev = tg[["game_id", "team", "home", "season", "day", "prev_gid"]].merge(
        actual[["game_id", "team", "playerId", "pos"]].rename(columns={"game_id": "prev_gid"}),
        on=["prev_gid", "team"]).drop(columns="prev_gid")
    return {"actual": actual, "prev": prev}

def ratings(pg: pd.DataFrame, lineup: pd.DataFrame, H: float, K5: float, K4: float, KI: float) -> pd.DataFrame:
    """Pre-game rating of each lineup row's player as of the lineup's game day (strictly earlier games only)."""
    pg = pg.assign(one=1.0)
    state = pd.concat([pg[["playerId", "day"]], _cum(pg, RATE_COLS, H, "r_"), _cum(pg, TOI_COLS, H_TOI, "u_")], axis=1)
    state = state.drop_duplicates(["playerId", "day"], keep="last").sort_values("day")
    q = lineup.reset_index(drop=True).assign(_i=lambda d: np.arange(len(d))).sort_values("day")
    m = pd.merge_asof(q, state.rename(columns={"day": "sday"}), left_on="day", right_on="sday", by="playerId",
                      allow_exact_matches=False, direction="backward").sort_values("_i")
    D = m["day"].to_numpy()
    fr, fu = np.power(2.0, -D / H), np.power(2.0, -D / H_TOI)
    S = {c: m[f"r_{c}"].fillna(0).to_numpy() * fr for c in RATE_COLS}
    U = {c: m[f"u_{c}"].fillna(0).to_numpy() * fu for c in TOI_COLS}
    out = m[["game_id", "team", "home", "season", "playerId", "pos"]].copy()
    isD = (out["pos"] == "D").to_numpy()
    for j, (c, name) in enumerate([("t5", "e5"), ("t4", "e4"), ("tall", "eall")]):
        dflt = np.where(isD, TOI_DEFAULT["D"][j], TOI_DEFAULT["F"][j])
        out[name] = (U[c] + K_TOI * dflt) / (U["one"] + K_TOI)
    out["off_rel"] = 3600 * S["relF"] / (S["t5r"] + K5)
    out["def_rel"] = -3600 * S["relA"] / (S["t5r"] + K5)
    out["off_raw"] = 3600 * S["rawF"] / (S["t5"] + K5)
    out["def_raw"] = -3600 * S["rawA"] / (S["t5"] + K5)
    out["pp"] = 3600 * S["ppd"] / (S["t4"] + K4)
    out["ixg"] = 3600 * S["ixd"] / (S["tall"] + KI)
    out["gs"] = 3600 * S["gsd"] / (S["tall"] + KI)
    out["exp_toi5"] = S["t5"] / 60.0      # decayed 5v5 minutes of history (experience)
    return out

def team_agg(r: pd.DataFrame, suffix: str) -> pd.DataFrame:
    r = r.copy()
    for c in ["off_rel", "def_rel", "off_raw", "def_raw"]:
        r[c + "_w"] = r[c] * r["e5"]
    r["pp_w"], r["ixg_w"], r["gs_w"] = r["pp"] * r["e4"], r["ixg"] * r["eall"], r["gs"] * r["eall"]
    r["new"] = (r["exp_toi5"] < 100).astype(float)
    g = r.groupby(["game_id", "team", "home", "season"])
    s = g[[c for c in r.columns if c.endswith("_w")] + ["e5", "e4", "eall", "new"]].sum()
    o = pd.DataFrame(index=s.index)
    for c in ["off_rel", "def_rel", "off_raw", "def_raw"]:
        o[c] = s[c + "_w"] / s["e5"]
    o["pp"] = s["pp_w"] / s["e4"]
    o["ixg"] = 5 * s["ixg_w"] / s["eall"]
    o["gs"] = 5 * s["gs_w"] / s["eall"]
    o["tot_rel"] = o["off_rel"] + o["def_rel"]
    o["tot_raw"] = o["off_raw"] + o["def_raw"]
    o["n_new"] = s["new"]
    # top-6 F / top-4 D by expected 5v5 TOI, rel total
    r["tot_rel"] = r["off_rel"] + r["def_rel"]
    r["rk"] = r.groupby(["game_id", "team", "pos"])["e5"].rank(ascending=False, method="first")
    top = r[((r["pos"] == "F") & (r["rk"] <= 6)) | ((r["pos"] == "D") & (r["rk"] <= 4))]
    o["top_rel"] = top.groupby(["game_id", "team", "home", "season"])["tot_rel"].mean()
    o.columns = [f"oi_{c}_{suffix}" for c in o.columns]
    return o.reset_index()

def features(pg, lus, H, K5, K4=12000.0, KI=18000.0) -> pd.DataFrame:
    parts = [team_agg(ratings(pg, lu, H, K5, K4, KI), name) for name, lu in lus.items()]
    return parts[0].merge(parts[1], on=["game_id", "team", "home", "season"])

def to_game_diffs(feat: pd.DataFrame, games: pd.DataFrame | None = None) -> pd.DataFrame:
    """home - away. With `games` (game_id, home_team_tri_code, away_team_tri_code) sides are keyed on team codes
    (MoneyPuck mislabels PHX home games as AWAY in 2011-2013); otherwise on MoneyPuck's home flag."""
    cols = [c for c in feat.columns if c.startswith("oi_")]
    if games is None:
        h = feat[feat["home"] == 1].set_index("game_id")[cols]
        a = feat[feat["home"] == 0].set_index("game_id")[cols]
        return (h - a).add_prefix("diff_").reset_index()
    f = feat.set_index(["game_id", "team"])[cols]
    g = games[["game_id", "home_team_tri_code", "away_team_tri_code"]]
    h = f.reindex(pd.MultiIndex.from_frame(g[["game_id", "home_team_tri_code"]])).to_numpy()
    a = f.reindex(pd.MultiIndex.from_frame(g[["game_id", "away_team_tri_code"]])).to_numpy()
    return pd.DataFrame(h - a, columns=["diff_" + c for c in cols]).assign(game_id=g["game_id"].to_numpy())

# ---------------- tuning (seasons <= 2020 only) / evaluation ----------------

def tune(pg, lus):
    """Pick (H, K5) by correlation of the prev-lineup diff with realised game xG differential, seasons 2010-2020."""
    tx = pg.groupby(["game_id", "home"])["ixg"].sum().unstack()
    target = (tx[1] - tx[0]).rename("xgd")
    res = []
    for H in [365.0, 730.0, 1460.0]:
        for K5 in [1000 * 60.0, 3000 * 60.0, 8000 * 60.0]:
            d = to_game_diffs(features(pg, {"prev": lus["prev"], "actual": lus["actual"]}, H, K5)).set_index("game_id")
            d = d.join(target)
            d = d[(d.index // 1000000 >= 2010) & (d.index // 1000000 <= 2020)]
            row = {"H": H, "K5min": K5 / 60}
            for c in ["tot_rel", "tot_raw", "ixg", "gs", "pp", "top_rel"]:
                row[c] = round(d[f"diff_oi_{c}_prev"].corr(d["xgd"]), 4)
            res.append(row)
            print(row, flush=True)
    return pd.DataFrame(res)

def _eval_subset(frame, cols, mask, test_seasons=(2022, 2023, 2024, 2025)):
    from sklearn.metrics import log_loss
    from predictions.train import _team_logistic
    out = []
    for t in test_seasons:
        tr, te = frame[frame["season"] < t - 1], frame[(frame["season"] == t) & mask]
        p = _team_logistic().fit(tr[cols], tr["home_win"].astype(int)).predict_proba(te[cols])[:, 1]
        m = te["mkt"].notna().to_numpy()
        out.append((log_loss(te["home_win"].astype(int), p, labels=[0, 1]),
                    log_loss(te["home_win"][m].astype(int), te["mkt"][m], labels=[0, 1]), len(te)))
    a = np.array(out)
    return {"model": round(a[:, 0].mean(), 4), "market": round(a[:, 1].mean(), 4), "n": int(a[:, 2].sum()),
            "per_season": [round(x, 4) for x in a[:, 0]]}

def main():
    from predictions import features as F
    from predictions.experiments.frames import evaluate
    pg = player_games()
    print("player-games", pg.shape, pg["season"].min(), pg["season"].max(), flush=True)
    lus = lineups(pg)
    if os.environ.get("OI_TUNE", "1") == "1":
        t = tune(pg, lus)
        t.to_csv(f"{SCRATCH}/oi_tune.csv", index=False)
        best = t.sort_values("tot_rel", ascending=False).iloc[0]
        H, K5 = float(best["H"]), float(best["K5min"]) * 60
    else:
        H, K5 = float(os.environ.get("OI_H", 365)), float(os.environ.get("OI_K5", 1000)) * 60
    print("using H", H, "K5 min", K5 / 60, flush=True)
    feat = features(pg, lus, H, K5)
    feat.to_pickle(f"{SCRATCH}/feat_onice.pkl")
    print("features", feat.shape, list(feat.columns), flush=True)

    frame = pd.read_pickle(f"{SCRATCH}/team_frame.pkl")
    diffs = to_game_diffs(feat, frame)
    frame = frame.merge(diffs, on="game_id", how="left")
    print("merge coverage", frame["diff_oi_tot_rel_prev"].notna().mean().round(4),
          frame.groupby("season")["diff_oi_tot_rel_prev"].apply(lambda s: s.notna().mean().round(3)).to_dict())
    new_base = list(F.TEAM_FEATURE_COLUMNS)
    old_base = [c for c in new_base if not c.startswith("diff_roster_")]
    sets = {"old_baseline": old_base, "new_baseline": new_base}
    extras = {"tot_rel": ["tot_rel"], "tot_raw": ["tot_raw"], "gs": ["gs"], "rel+pp": ["tot_rel", "pp"],
              "rel+raw+pp+gs": ["tot_rel", "tot_raw", "pp", "gs"],
              "all": ["off_rel", "def_rel", "off_raw", "def_raw", "pp", "ixg", "gs", "top_rel"]}
    for v in ["prev", "actual"]:
        for name, extra in extras.items():
            if v == "actual" and name not in ("tot_rel", "rel+raw+pp+gs", "all"):
                continue
            for bname, b in (("old", old_base), ("new", new_base)):
                sets[f"{bname}+{v}:{name}"] = b + [f"diff_oi_{c}_{v}" for c in extra]
    early = (frame["home_games_season"] < 10)
    rows = []
    for k, cols in sets.items():
        r = evaluate(frame, cols)
        e = _eval_subset(frame, cols, early)
        rows.append({"set": k, "mean": round(r["mean_model"], 4), "market": round(r["mean_market"], 4),
                     "per_season": [round(r[t]["model"], 4) for t in (2022, 2023, 2024, 2025)],
                     "early10": e["model"], "early10_mkt": e["market"], "early_n": e["n"],
                     "early_per_season": e["per_season"]})
        print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv(f"{SCRATCH}/oi_eval.csv", index=False)

if __name__ == "__main__":
    main()
