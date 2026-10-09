"""Age-adjusted and time-decayed skater ratings in the team model (roster rating), on the shared frame.

    python -m predictions.experiments.age_ratings [--variants base hl365 target delta ...]

Rebuilds the roster-rating columns of /scratch/c_age/team_frame.pkl (frames.build at the current code) for each
`skater_ratings` variant, then scores the regular season 2022-25 (frames.evaluate) and each test season's first
10 games per team (roster_eval.early).
"""
import argparse
import asyncio
import os
import pandas as pd
from app.database import AsyncSessionLocal
from predictions import features as F
from predictions.data import load_skater_logs, load_team_stats
from predictions.experiments import frames
from predictions.experiments.roster_eval import ROSTER_COLS, attach, early

DIR = "/scratch/c_age"
VARIANTS = {"base": (None, None), "hl365": (365, None), "hl548": (548, None), "hl730": (730, None),
            "aging": (None, "aging"), "aging_hl730": (730, "aging"), "aging_hl365": (365, "aging")}
# dropped after a first run (no gain): shrinking toward a cross-sectional position x age league rate ("target"),
# and that curve plus the skater's shrunk excess over it ("delta")

async def _load():
    async with AsyncSessionLocal() as db:
        return await load_skater_logs(db), await load_team_stats(db)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="*", default=list(VARIANTS))
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()
    os.makedirs(DIR, exist_ok=True)
    fpath, spath = f"{DIR}/team_frame.pkl", f"{DIR}/skaters_teams.pkl"
    if args.rebuild or not os.path.exists(fpath):
        frames.build().to_pickle(fpath)
    if args.rebuild or not os.path.exists(spath):
        pd.to_pickle(asyncio.run(_load()), spath)
    frame = pd.read_pickle(fpath)
    skaters, team_stats = pd.read_pickle(spath)
    print("birth dates known for", round(skaters["birth_date"].notna().mean(), 4), "of skater rows", flush=True)
    drop = [f"{p}_{c}" for p in ("home", "away", "diff") for c in ROSTER_COLS + ["roster_n"]]
    frame = frame.drop(columns=[c for c in drop if c in frame])
    team_games = F.build_team_games(team_stats)
    lineups = F.expected_lineups(skaters, team_games)
    cols = F.TEAM_FEATURE_COLUMNS
    for name in args.variants:
        hl, mode = VARIANTS[name]
        f = attach(frame, F.roster_ratings(lineups, F.skater_ratings(skaters, hl, mode)), name)
        r = frames.evaluate(f, cols)
        print(f"  {name:<14} " + " ".join(f"{t}:{r[t]['model']:.4f}" for t in frames.TEST_SEASONS),
              f"mean {r['mean_model']:.4f}  first10 {early(f, cols)[0]:.4f}", flush=True)
