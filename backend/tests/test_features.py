import numpy as np
import pandas as pd
from predictions import features as F

def _team_offense():
    rows = []
    for i, date in enumerate([20251010, 20251012, 20251015, 20251018]):
        for team, opp, home, gf in (("AAA", "BBB", 1.0, 3 + i), ("BBB", "AAA", 0.0, 2)):
            rows.append({"game_id": 100 + i, "team": team, "opponent": opp, "season": 2025, "game_date": date,
                         "is_home": home, "gf": float(gf), "ga": 2.0, "xgf": 2.5, "xga": 2.5, "saf": 50.0, "saa": 50.0,
                         "xgf5": 2.0, "xga5": 2.0, "cf5": 40.0, "ca5": 40.0, "gf5": 2.0, "ga5": 2.0})
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

def _skater_rows():
    # AAA's games 100 and 101; player 1 plays both, player 2 only the first, player 3 only the second
    rows = [(100, 1, 20251010), (100, 2, 20251010), (101, 1, 20251012), (101, 3, 20251012)]
    return pd.DataFrame([{"game_id": g, "team": "AAA", "player_id": p, "game_date": d, "position": "C",
                          "game_score": 1.0, "points": 1.0, "toi": 900.0, "on_ice_x_goals_percentage": 0.5}
                         for g, p, d in rows])

def test_expected_lineup_is_previous_game_this_season():
    team_games = pd.DataFrame({"game_id": [100, 101, 102], "team": "AAA", "season": 2025,
                               "date": pd.to_datetime(["2025-10-10", "2025-10-12", "2025-10-14"])})
    lineups = F.expected_lineups(_skater_rows(), team_games)
    by_game = lineups.groupby("game_id")["player_id"].apply(set).to_dict()
    assert by_game[100] == {1, 2}       # season opener: its own (opening-night) lineup
    assert by_game[101] == {1, 2}       # previous game's lineup, not who actually played
    assert by_game[102] == {1, 3}       # upcoming game: latest lineup

def test_roster_ratings_use_only_earlier_games():
    skaters = _skater_rows()
    ratings = F.skater_ratings(skaters)
    lineups = pd.DataFrame({"game_id": [101, 101], "team": "AAA", "player_id": [1, 2],
                            "date": pd.to_datetime(["2025-10-12", "2025-10-12"])})
    before = F.roster_ratings(lineups, ratings)
    skaters.loc[skaters["game_id"] == 101, "game_score"] = 50.0   # game 101's own result must not leak in
    after = F.roster_ratings(lineups, F.skater_ratings(skaters))
    pd.testing.assert_frame_equal(before, after)
    assert before["roster_n"].item() == 2

def test_roster_lineups_pick_12_forwards_and_6_defense():
    rosters = pd.DataFrame({"player_id": range(25), "team": "AAA",
                            "position": ["C"] * 14 + ["D"] * 8 + ["G"] * 3})
    ratings = pd.DataFrame({"player_id": range(25), "exp_toi": np.linspace(0.1, 0.4, 25)})
    games = pd.DataFrame({"game_id": [200], "team": ["AAA"], "date": pd.to_datetime(["2025-10-01"])})
    picked = F.roster_lineups(rosters, games, ratings).merge(rosters, on=["player_id", "team"])
    assert picked["position"].value_counts().to_dict() == {"C": 12, "D": 6}

def test_team_training_rows_include_playoffs():
    from predictions.train import _team_training_rows
    df = pd.DataFrame({
        "game_id": [2024020001, 2024030111, 2024010001, 2024020002, 2024020003],
        "home_win": [1.0, 0.0, 1.0, np.nan, 1.0], "home_games_season": [5, 85, 1, 6, np.nan],
    })
    # regular season and playoffs; not preseason, unplayed games or rows without team history
    assert list(_team_training_rows(df)["game_id"]) == [2024020001, 2024030111]
