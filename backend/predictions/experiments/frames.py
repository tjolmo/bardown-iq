"""Shared evaluation frame for team-model experiments, built with the production feature code from the DB.

    python -m predictions.experiments.frames --out /scratch/team_frame.pkl

One row per finished regular-season game with every production team feature, the label (`home_win`), and the
market's vig-free closing (`mkt`) / opening (`mkt_open`) home win probabilities and median prices where known.
Experiments add their own feature columns by merging on `game_id`, then score with `evaluate`.
"""
import argparse
import asyncio
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss
from app.database import AsyncSessionLocal
from app.models import GameOdds
from sqlalchemy import select
from predictions import features as F
from predictions.data import load_team_stats, load_games, load_goalie_logs, load_skater_logs
from predictions.train import _team_logistic

TEST_SEASONS = [2022, 2023, 2024, 2025]

async def _load():
    async with AsyncSessionLocal() as db:
        odds = pd.DataFrame([dict(r) for r in (await db.execute(select(
            GameOdds.game_id, GameOdds.home_prob_novig.label("mkt"), GameOdds.open_home_prob_novig.label("mkt_open"),
            GameOdds.home_moneyline, GameOdds.away_moneyline, GameOdds.open_home_moneyline, GameOdds.open_away_moneyline,
            GameOdds.total_line))).mappings().all()])
        return await load_team_stats(db), await load_games(db), await load_goalie_logs(db), await load_skater_logs(db), odds

def build() -> pd.DataFrame:
    team_stats, games, goalies, skaters, odds = asyncio.run(_load())
    team_games = F.build_team_games(team_stats)
    roster = F.roster_ratings(F.expected_lineups(skaters, team_games), F.skater_ratings(skaters))
    frame = F.build_team_model_frame(games, F.team_history_features(team_games),
                                     [F.starter_features(team_games, goalies), roster])
    frame = frame[(frame["game_id"] // 10000 % 100 == 2) & frame["home_win"].notna() & frame["home_games_season"].notna()]
    return frame.merge(odds, on="game_id", how="left").reset_index(drop=True)

def evaluate(frame: pd.DataFrame, cols: list[str], model_factory=_team_logistic, test_seasons=TEST_SEASONS) -> dict:
    """Rolling-origin: for each test season, fit on all seasons before the previous one (that one is reserved for
    early stopping / stacking), score on the test season. Returns per-season log loss and the mean, plus the
    market's log loss on the same games where it has a line."""
    out = {}
    for test in test_seasons:
        tr, te = frame[frame["season"] < test - 1], frame[frame["season"] == test]
        p = model_factory().fit(tr[cols], tr["home_win"].astype(int)).predict_proba(te[cols])[:, 1]
        m = te["mkt"].notna().to_numpy()
        out[test] = {"model": log_loss(te["home_win"], p), "market": log_loss(te["home_win"][m], te["mkt"][m]),
                     "model_on_market_games": log_loss(te["home_win"][m], p[m])}
    out["mean_model"] = float(np.mean([out[t]["model"] for t in test_seasons]))
    out["mean_market"] = float(np.mean([out[t]["market"] for t in test_seasons]))
    return out

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/scratch/team_frame.pkl")
    args = ap.parse_args()
    frame = build()
    frame.to_pickle(args.out)
    r = evaluate(frame, F.TEAM_FEATURE_COLUMNS)
    print(len(frame), "games;", {k: (round(v["model"], 4), round(v["market"], 4)) if isinstance(v, dict) else round(v, 4) for k, v in r.items()})
