import numpy as np
import pandas as pd
from predictions import features as F

def _logs():
    """Two teams' skaters over three games; player 1 (AAA forward) is the one under test."""
    rows = []
    for i, (gid, date) in enumerate([(100, 20251010), (101, 20251012), (102, 20251014)]):
        for team, opp, home in (("AAA", "BBB", 1.0), ("BBB", "AAA", 0.0)):
            for k, pos in enumerate(["C", "L", "D", "D"]):
                pid = (1 if team == "AAA" else 11) + k
                rows.append({"game_id": gid, "player_id": pid, "season": 2025, "game_date": date, "team": team,
                             "opponent": opp, "is_home": home, "position": pos, "goals": 1, "primary_assists": 0,
                             "secondary_assists": 0, "points": 1, "x_goals": 0.5 + k, "toi": 1000.0 - 100 * k,
                             "shot_attempts": 3, "high_danger_shots": 1, "on_ice_x_goals_percentage": 0.5,
                             "game_score": 1.0, "shots_on_goal": 2 + k, "pp_toi": 120.0 if k < 2 else 0.0,
                             "pp_points": 0})
    return pd.DataFrame(rows)

def test_shares_are_within_team_and_game():
    s = F.skater_shares(_logs()).set_index(["game_id", "player_id"])
    # team PP time = summed skater PP time / 5 skaters on the ice
    assert s.loc[(100, 1), "pp_share"] == 120 / (240 / 5)
    assert s.loc[(100, 1), "sog_share"] == 2 / (2 + 3 + 4 + 5)
    # ice-time rank is within forwards / defensemen separately
    assert s.loc[(100, 1), "toi_rank"] == 1 and s.loc[(100, 3), "toi_rank"] == 1 and s.loc[(100, 4), "toi_rank"] == 2

NO_TEAM_CONTEXT = pd.DataFrame(columns=["game_id", "team"] + F.CONTEXT_TEAM_COLUMNS)

def test_share_features_use_only_prior_games():
    logs = _logs()
    base, _ = F.skater_features(logs, NO_TEAM_CONTEXT, shares=F.skater_shares(logs))
    changed_logs = logs.copy()
    # game 102's own deployment (even a teammate's, which changes the team totals) must not leak in
    changed_logs.loc[(changed_logs["game_id"] == 102) & (changed_logs["player_id"] == 2), ["shots_on_goal", "pp_toi"]] = 50
    changed_logs.loc[(changed_logs["game_id"] == 102) & (changed_logs["player_id"] == 1), "toi"] = 10.0
    changed, _ = F.skater_features(changed_logs, NO_TEAM_CONTEXT,
                                   shares=F.skater_shares(changed_logs))
    key = (base["game_id"] == 102) & (base["player_id"] == 1)
    pd.testing.assert_frame_equal(base.loc[key, F.SKATER_SHARE_COLUMNS], changed.loc[key, F.SKATER_SHARE_COLUMNS])
    assert base.loc[key, "sog_share_season"].item() == 2 / 14

def test_teammate_quality_excludes_the_player():
    lineups = pd.DataFrame({"game_id": 200, "team": "AAA", "player_id": range(1, 20),
                            "exp_toi": np.linspace(0.4, 0.1, 19), "exp_game_score": np.arange(1.0, 20.0),
                            "exp_points": 0.5})
    lineups = lineups.groupby(["game_id", "team"]).head(F.LINEUP_SIZE)     # rated lineups keep the top 18
    players = pd.DataFrame({"game_id": [200, 200], "team": "AAA", "player_id": [5, 99]})
    q = F.teammate_quality(players, lineups).set_index("player_id")
    total = sum(range(1, 19))
    assert q.loc[5, "teammates_game_score"] == total - 5            # the other 17
    assert q.loc[99, "teammates_game_score"] == total - 18          # not expected to dress: the top 17
    assert q.loc[5, "teammates_points"] == 17 * 0.5

def test_teammate_quality_uses_only_earlier_games():
    logs = _logs()
    before = F.teammate_quality(logs, F.played_lineups(logs, F.skater_ratings(logs)))
    logs.loc[logs["game_id"] == 102, "game_score"] = 50.0
    after = F.teammate_quality(logs, F.played_lineups(logs, F.skater_ratings(logs)))
    key = before["game_id"] == 102
    pd.testing.assert_frame_equal(before[key], after[key])
