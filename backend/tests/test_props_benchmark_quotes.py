import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from predictions.experiments.props_benchmark import consensus_markets, run
from predictions.vig import devig_two_way


def q(book, side, line, odds, player=8, prop="player_points"):
    return dict(game_id=1, player_id=player, prop_type=prop, over_under=side, line=line, bookmaker=book, odds=odds,
                season=20262027, last_seen=pd.Timestamp("2026-10-07 18:00", tz="UTC"),
                start_time=pd.Timestamp("2026-10-07 23:00", tz="UTC"))


def test_consensus_line_best_prices_and_mean_fair_prob():
    quotes = pd.DataFrame([q("dk", "Over", 0.5, -150), q("dk", "Under", 0.5, 120),
                           q("fd", "Over", 0.5, -140), q("fd", "Under", 0.5, 110),
                           q("mgm", "Over", 1.5, 250), q("mgm", "Under", 1.5, -330),
                           q("dk", "Yes", 0.5, 150, prop="player_goal_scorer_anytime")])
    quotes["season"] = quotes["season"] // 10000
    m = consensus_markets(quotes, "shin").set_index("prop_type")
    pts = m.loc["points"]
    assert (pts["line"], pts["over_price"], pts["under_price"], pts["n_books"]) == (0.5, -140, 120, 2)
    fair = devig_two_way([-150, -140], [120, 110], "shin").mean()
    assert np.isclose(pts["market_p"], fair)
    anytime = m.loc["anytime_goal"]
    assert anytime["over_price"] == 150 and np.isnan(anytime["under_price"])


def test_post_start_quotes_dropped_and_empty_input_gives_no_markets():
    late = q("dk", "Over", 0.5, -150)
    late["last_seen"] = pd.Timestamp("2026-10-08 01:00", tz="UTC")
    assert consensus_markets(pd.DataFrame([late]), "shin").empty
    empty = pd.DataFrame(columns=list(late))
    assert consensus_markets(empty, "shin").empty


def test_run_scores_new_skater_targets_from_second_predictions_file():
    props = pd.DataFrame([
        dict(game_id=g, player_id=8, prop_type=pt, line=line, book="b", over_price=-120, under_price=100,
             open_line=None, open_over_price=None, open_under_price=None, sides_inferred=False, season=2025)
        for g in range(40) for pt, line in (("hits", 1.5), ("blocked_shots", 0.5), ("pp_points", 0.5))
    ] + [dict(game_id=g, player_id=8, prop_type="anytime_goal", line=0.5, book="b", over_price=200, under_price=None,
              open_line=None, open_over_price=None, open_under_price=None, sides_inferred=False, season=2025)
         for g in range(40)])
    rng = np.random.default_rng(0)
    base = pd.DataFrame({"game_id": range(40), "player_id": 8, "goals": rng.poisson(0.3, 40),
                         "pred_v_goals": 0.3})
    extra = pd.DataFrame({"game_id": range(40), "player_id": 8, "hits": rng.poisson(2, 40),
                          "blocked_shots": rng.poisson(1, 40), "pp_points": rng.poisson(0.3, 40),
                          "pred_v_hits": 2.0, "pred_v_blocked_shots": 1.0, "pred_v_pp_points": 0.3})
    report = run(props, {"skater": [base, extra], "goalie": []}, {"skater": "v", "goalie": "v"}, "shin", {})
    for pt in ("hits", "blocked_shots", "pp_points"):
        assert report[pt]["two_sided"]["n"] == 40
    assert report["anytime_goal"]["one_sided"]["n"] == 40
    # anytime goal is P(goals >= 1) under the goals rate
    assert np.isclose(report["anytime_goal"]["one_sided"]["model_mean_p"], round(1 - np.exp(-0.3), 4))
