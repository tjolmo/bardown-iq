import numpy as np
import pandas as pd
from predictions import features as F

def _team_offense():
    rows = []
    for i, date in enumerate([20251010, 20251012, 20251015, 20251018]):
        for team, opp, home, gf in (("AAA", "BBB", 1.0, 3 + i), ("BBB", "AAA", 0.0, 2)):
            rows.append({"game_id": 100 + i, "team": team, "opponent": opp, "season": 2025, "game_date": date,
                         "is_home": home, "gf": float(gf), "xgf": 2.5, "saf": 50.0, "hdf": 10.0})
    return pd.DataFrame(rows)

def test_team_features_use_only_prior_games():
    base = F.team_history_features(F.build_team_games(_team_offense()))
    changed_offense = _team_offense()
    changed_offense.loc[changed_offense["game_id"] == 103, "gf"] = 99.0
    changed = F.team_history_features(F.build_team_games(changed_offense))
    key = (base["game_id"] == 103) & (base["team"] == "AAA")
    # a game's own result must not leak into its pre-game features
    pd.testing.assert_frame_equal(base[key], changed[key])
    # AAA scored 3, 4, 5 in its first three games
    assert base.loc[key, "team_gf_season"].item() == 4.0
    assert base.loc[key, "team_games_season"].item() == 3

def test_appended_upcoming_games_do_not_dilute_means():
    offense = _team_offense()
    upcoming = pd.DataFrame([
        {"game_id": 200 + i, "team": "AAA", "opponent": "BBB", "season": 2025, "game_date": d, "is_home": 1.0}
        for i, d in enumerate([20251020, 20251022])
    ])
    feats = F.team_history_features(F.build_team_games(pd.concat([offense, upcoming], ignore_index=True)))
    later = feats[(feats["game_id"] == 201)]
    # the unplayed game 200 doesn't count as a played game with zero goals
    assert later["team_gf_season"].item() == np.mean([3, 4, 5, 6])
    assert later["team_games_season"].item() == 4

def test_elo_updates_only_on_finished_games():
    games = pd.DataFrame({
        "id": [1, 2, 3], "season": [2025] * 3, "date": [20251010, 20251012, 20251014],
        "home_team_tri_code": ["AAA", "AAA", "AAA"], "away_team_tri_code": ["BBB", "BBB", "BBB"],
        "home_score": [5, np.nan, np.nan], "away_score": [1, np.nan, np.nan],
    })
    elo = F.elo_ratings(games).set_index("game_id")
    assert elo.loc[1, "home_elo"] == 1500.0
    assert elo.loc[2, "home_elo"] > 1500.0 > elo.loc[2, "away_elo"]
    # game 2 is unplayed, so game 3 sees the same ratings
    assert elo.loc[3, "home_elo"] == elo.loc[2, "home_elo"]

def test_placeholder_games_skip_stale_unfinished_games(monkeypatch):
    from predictions import predict
    monkeypatch.setattr(predict, "_today", lambda: 20251020)
    games = pd.DataFrame({
        "id": [1, 2, 3, 4], "date": [20251010, 20251015, 20251018, 20251022],
        "home_score": [3.0, np.nan, 2.0, np.nan],
    })
    # 1 has logs; 2 was postponed (past, never finished); 3 finished but isn't scraped yet; 4 is upcoming
    assert list(predict._placeholder_games(games, {1})["id"]) == [3, 4]
