"""Checks that skater predictions from the precomputed shares (skater_game_shares) equal the v4 computation.

For every skater the afternoon log would predict on `--date`, runs `predict.predict_skater` (stored shares, lineups
cut to the player's games) and a copy of the v4 code (shares from every teammate's log of every past game, the
season's full lineups), and compares the model inputs and the expected counts.

    python -m predictions.experiments.shares_equivalence --date 20261008
"""
import argparse
import asyncio
import json
import types

import numpy as np
import pandas as pd

from predictions import features as F, predict as P, prediction_log as L
from predictions.config import SKATER_BUNDLE
from predictions.data import load_game_mates, load_skater_logs, load_games


async def v4_predict_skater(db, player_id: int, team: str, game) -> tuple[dict, pd.DataFrame]:
    """predict_skater as of model-v4 (commit 013b654), returning the model inputs too."""
    bundle = P.load_bundle(SKATER_BUNDLE)
    logs = await load_skater_logs(db, [player_id])
    ctx = await P._team_context(db)
    upcoming = P._upcoming_player_rows(logs, game, team, ctx["placeholders"])
    shares = F.skater_shares(await load_game_mates(db, logs["game_id"].unique().tolist()))
    df, _ = F.skater_features(pd.concat([logs, upcoming], ignore_index=True), ctx["team_feats"],
                              league_rates=bundle["league_rates"], extra_stats=bundle.get("extra_stats", ()),
                              shares=shares, lineups=ctx.get("lineups"))
    X = df.loc[df["game_id"] == game.id, bundle["features"]].tail(1).astype(np.float32)
    trends = bundle.get("trends", {})
    expected = {t: float(m.predict(X, base_margin=np.log([trends[t]]) if t in trends else None)[0])
                for t, m in bundle["models"].items()}
    return expected, X


async def _run(date: int) -> dict:
    from app.database import AsyncSessionLocal
    bundle = P.load_bundle(SKATER_BUNDLE)
    captured = {}
    skater_features = F.skater_features

    def capture(*a, **k):
        out = skater_features(*a, **k)
        captured["df"] = out[0]
        return out
    async with AsyncSessionLocal() as db:
        games = await load_games(db)
        slate = games[games["date"] == date]
        stored_players = 0
        rows = []
        for g in slate.itertuples():
            game = types.SimpleNamespace(id=int(g.id), date=int(g.date), season=int(g.season) * 10001 + 1,
                                         home_team_tri_code=g.home_team_tri_code, away_team_tri_code=g.away_team_tri_code)
            dressing = await L._expected_skaters(db, game)
            for pid, team, pos in await L._roster(db, [game.home_team_tri_code, game.away_team_tri_code]):
                if pos == "G" or (dressing and pid not in dressing):
                    continue
                logs = await load_skater_logs(db, [pid])
                if logs.empty:
                    continue
                stored = await P._load_shares(db, pid, logs["game_id"].unique().tolist())
                stored_players += int(stored is not None and len(stored) == logs["game_id"].nunique())
                F.skater_features = capture
                try:
                    new = await P.predict_skater(db, pid, team, game)
                finally:
                    F.skater_features = skater_features
                df = captured["df"]
                X_new = df.loc[df["game_id"] == game.id, bundle["features"]].tail(1).astype(np.float32)
                old, X_old = await v4_predict_skater(db, pid, team, game)
                a, b = X_new.to_numpy(np.float64), X_old.to_numpy(np.float64)
                same_nan = bool((np.isnan(a) == np.isnan(b)).all())
                rows.append({"player_id": pid, "game_id": game.id, "same_nan": same_nan,
                             "max_feature_diff": float(np.nanmax(np.abs(a - b), initial=0.0)),
                             "max_pred_diff": max(abs(new[t] - old[t]) for t in old),
                             "max_pred_rel_diff": max(abs(new[t] - old[t]) / max(abs(old[t]), 1e-12) for t in old)})
    r = pd.DataFrame(rows)
    return {"date": date, "skaters": len(r), "fully_stored": stored_players,
            "nan_pattern_mismatches": int((~r["same_nan"]).sum()),
            "max_feature_diff": float(r["max_feature_diff"].max()), "max_pred_diff": float(r["max_pred_diff"].max()),
            "max_pred_rel_diff": float(r["max_pred_rel_diff"].max()),
            "bitwise_equal_predictions": int((r["max_pred_diff"] == 0).sum())}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=int, required=True)
    print(json.dumps(asyncio.run(_run(parser.parse_args(argv).date)), indent=1))


if __name__ == "__main__":
    main()
