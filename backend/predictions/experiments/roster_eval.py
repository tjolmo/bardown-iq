"""Does a roster-based team rating help the win model? Uses the shared frame from frames.py.
    python -m predictions.experiments.roster_eval
"""
import asyncio
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss
from app.database import AsyncSessionLocal
from predictions import features as F
from predictions.data import load_skater_logs, load_team_stats
from predictions.experiments.frames import evaluate

ROSTER_COLS = ["roster_game_score", "roster_points", "roster_xg_pct"]

async def _load():
    async with AsyncSessionLocal() as db:
        return await load_skater_logs(db), await load_team_stats(db)

def roster_frame(skaters, team_stats, actual=False) -> pd.DataFrame:
    team_games = F.build_team_games(team_stats)
    ratings = F.skater_ratings(skaters)
    if actual:
        lineups = skaters.assign(date=F._date(skaters["game_date"]))[["game_id", "team", "date", "player_id"]]
    else:
        lineups = F.expected_lineups(skaters, team_games)
    return F.roster_ratings(lineups, ratings)

def attach(frame, roster, tag):
    out = frame
    for side in ("home", "away"):
        r = roster.rename(columns={c: f"{side}_{c}" for c in ROSTER_COLS + ["roster_n"]})
        out = out.merge(r.rename(columns={"team": f"{side}_team_tri_code"}), on=["game_id", f"{side}_team_tri_code"], how="left")
    for c in ROSTER_COLS:
        out[f"diff_{c}"] = out[f"home_{c}"] - out[f"away_{c}"]
    return out

def early(frame, cols):
    """Log loss on each test season's first 10 games per team, where roster changes matter most."""
    from predictions.train import _team_logistic
    res = []
    for test in (2022, 2023, 2024, 2025):
        tr, te = frame[frame.season < test - 1], frame[(frame.season == test) & (frame.home_games_season < 10)]
        p = _team_logistic().fit(tr[cols], tr.home_win.astype(int)).predict_proba(te[cols])[:, 1]
        res.append(log_loss(te.home_win, p))
    m = frame[(frame.season.isin([2022, 2023, 2024, 2025])) & (frame.home_games_season < 10) & frame.mkt.notna()]
    return round(float(np.mean(res)), 4), round(float(log_loss(m.home_win, m.mkt)), 4)

if __name__ == "__main__":
    skaters, team_stats = asyncio.run(_load())
    frame = pd.read_pickle("/scratch/team_frame.pkl")
    base = F.TEAM_FEATURE_COLUMNS
    for tag, actual in (("prev", False), ("actual", True)):
        roster = roster_frame(skaters, team_stats, actual)
        roster.to_pickle(f"/scratch/feat_roster_{tag}.pkl")
        f = attach(frame, roster, tag)
        print(tag, "coverage", round(f["home_roster_game_score"].notna().mean(), 4), "mean lineup", round(f["home_roster_n"].mean(), 1))
        variants = {"base": base, "+gs": base + ["diff_roster_game_score"], "+pts": base + ["diff_roster_points"],
                    "+xg": base + ["diff_roster_xg_pct"], "+all": base + [f"diff_{c}" for c in ROSTER_COLS],
                    "roster_only+elo": ["elo_diff", "home_rest_days", "away_rest_days"] + [f"diff_{c}" for c in ROSTER_COLS]}
        for name, cols in variants.items():
            r = evaluate(f, cols)
            print(f"  {tag:<6} {name:<16} " + " ".join(f"{t}:{r[t]['model']:.4f}" for t in (2022, 2023, 2024, 2025)),
                  f"mean {r['mean_model']:.4f} (market {r['mean_market']:.4f})  first10 {early(f, cols)}", flush=True)
