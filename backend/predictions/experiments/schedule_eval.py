"""Schedule / fatigue / travel features on top of the production team model.

Groups are scored one at a time on selection seasons (<= 2021), combined greedily there, then the chosen set is
confirmed on the 2022-2025 test seasons.
    python -m predictions.experiments.schedule_eval --frame /scratch/team_frame.pkl --out /scratch/feat_schedule.pkl
"""
import argparse
import asyncio
import numpy as np
import pandas as pd
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import Games
from predictions import features as F
from predictions.data import load_games
from predictions.experiments.frames import evaluate, TEST_SEASONS
from predictions.experiments.schedule_features import schedule_features

SELECT_SEASONS = [2018, 2019, 2021]

async def _load() -> pd.DataFrame:
    async with AsyncSessionLocal() as db:
        games = await load_games(db)
        venues = pd.DataFrame((await db.execute(select(Games.id, Games.venue))).mappings().all())
    return games.merge(venues, on="id")

def _transform(s: pd.DataFrame) -> pd.DataFrame:
    """Linear-model-friendly versions of the raw features."""
    out = s[["game_id", "team"]].copy()
    out["log_travel"] = np.log1p(s["travel_km"])
    out["log_travel_7d"] = np.log1p(s["travel_km_7d"])
    out["tz_shift"] = s["tz_shift"]
    out["tz_abs"] = s["tz_shift"].abs()
    out["games_4d"], out["games_7d"] = s["games_4d"], s["games_7d"]
    out["three_in_four"] = (s["games_4d"] >= 3).astype(int)
    out["back_to_back"], out["b2b_travel"] = s["back_to_back"], s["b2b_travel"]
    out["log_trip"] = np.log1p(s["road_trip_game"])
    out["log_stand"] = np.log1p(s["home_stand_game"])
    out["first_home_after_trip"] = s["first_home_after_trip"]
    out["log_prev_trip"] = np.log1p(s["prev_trip_len"])
    out["season_day"] = s["season_day"]
    return out

GROUPS = {
    "travel": ["log_travel"],
    "travel_7d": ["log_travel_7d"],
    "tz": ["tz_shift", "tz_abs"],
    "density": ["games_4d", "games_7d"],
    "three_in_four": ["three_in_four"],
    "b2b": ["back_to_back", "b2b_travel"],
    "trip": ["log_trip", "log_stand"],
    "homecoming": ["first_home_after_trip", "log_prev_trip"],
}

def _join(frame: pd.DataFrame, t: pd.DataFrame) -> pd.DataFrame:
    for side in ("home", "away"):
        side_feats = t.rename(columns={c: f"{side}_s_{c}" for c in t.columns if c not in ("game_id", "team")})
        frame = frame.merge(side_feats.rename(columns={"team": f"{side}_team_tri_code"}),
                            on=["game_id", f"{side}_team_tri_code"], how="left")
    for c in t.columns.drop(["game_id", "team"]):
        frame[f"diff_s_{c}"] = frame[f"home_s_{c}"] - frame[f"away_s_{c}"]
    return frame

def _cols(group_names) -> list[str]:
    # the side-specific trip features only make sense for the side that has them (away trips, home stands)
    out = []
    for g in group_names:
        for c in GROUPS[g]:
            if c in ("log_trip",):
                out.append(f"away_s_{c}")
            elif c in ("log_stand", "first_home_after_trip", "log_prev_trip"):
                out.append(f"home_s_{c}")
            else:
                out += [f"home_s_{c}", f"away_s_{c}"]
    return out

def _fmt(r: dict, seasons) -> str:
    return f"mean {r['mean_model']:.4f} | " + " ".join(f"{s}:{r[s]['model']:.4f}" for s in seasons)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", default="/scratch/team_frame.pkl")
    ap.add_argument("--out", default="/scratch/feat_schedule.pkl")
    args = ap.parse_args()
    feats = schedule_features(asyncio.run(_load()))
    frame = _join(pd.read_pickle(args.frame), _transform(feats))
    assert frame["home_s_log_travel"].notna().all()
    base = F.TEAM_FEATURE_COLUMNS

    # early seasons have no market lines, which evaluate() can't score; a dummy keeps it running (market ignored there)
    sel_frame = frame.assign(mkt=frame["mkt"].fillna(0.5))

    def score(extra, seasons):
        return evaluate(sel_frame if seasons == SELECT_SEASONS else frame, base + extra, test_seasons=seasons)

    sel_base = score([], SELECT_SEASONS)["mean_model"]
    print("selection seasons", SELECT_SEASONS, "baseline", _fmt(score([], SELECT_SEASONS), SELECT_SEASONS))
    gains = {}
    for name in GROUPS:
        r = score(_cols([name]), SELECT_SEASONS)
        gains[name] = sel_base - r["mean_model"]
        print(f"  +{name:14s} {_fmt(r, SELECT_SEASONS)}  gain {gains[name]:+.5f}")

    # greedy forward selection on the selection seasons
    chosen, best = [], sel_base
    for name in sorted(gains, key=gains.get, reverse=True):
        r = score(_cols(chosen + [name]), SELECT_SEASONS)["mean_model"]
        if r < best - 1e-5:
            chosen, best = chosen + [name], r
    print("chosen", chosen, f"selection mean {best:.4f} (baseline {sel_base:.4f})")

    print("test seasons", TEST_SEASONS)
    rb = score([], TEST_SEASONS)
    print("  baseline      ", _fmt(rb, TEST_SEASONS), f"market {rb['mean_market']:.4f}")
    for name in GROUPS:
        print(f"  +{name:14s}", _fmt(score(_cols([name]), TEST_SEASONS), TEST_SEASONS))
    print("  +chosen       ", _fmt(score(_cols(chosen), TEST_SEASONS), TEST_SEASONS), _cols(chosen))
    print("  +all          ", _fmt(score(_cols(list(GROUPS)), TEST_SEASONS), TEST_SEASONS))
    feats.to_pickle(args.out)
    print("saved", len(feats), "rows to", args.out)
