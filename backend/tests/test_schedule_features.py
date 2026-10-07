import pandas as pd
from predictions.experiments.schedule_features import schedule_features

def _games(rows, venue=None):
    df = pd.DataFrame(rows, columns=["date", "home_team_tri_code", "away_team_tri_code"])
    df["id"] = 2025020001 + df.index
    df["season"] = 2025
    if venue is not None:
        df["venue"] = venue
    return df

def _team(feats, team):
    return feats[feats["team"] == team].reset_index(drop=True)

def test_road_trip_travel_and_fatigue():
    # BOS: home, then at NYR and PHI on back-to-back nights, at VAN, then home
    feats = schedule_features(_games([(20251010, "BOS", "TOR"), (20251012, "NYR", "BOS"), (20251013, "PHI", "BOS"),
                                      (20251016, "VAN", "BOS"), (20251018, "BOS", "MTL")]))
    bos = _team(feats, "BOS")
    assert bos["travel_km"][0] == 0                       # season starts at home
    assert 250 < bos["travel_km"][1] < 320                # Boston -> New York
    assert bos["back_to_back"].tolist() == [0, 0, 1, 0, 0]
    assert bos["b2b_travel"].tolist() == [0, 0, 1, 0, 0]
    assert bos["games_4d"][2] == 3 and bos["games_7d"][3] == 4   # 3 in 4 nights, 4 in 7
    assert bos["tz_shift"].tolist() == [0, 0, 0, -3, 3]
    assert bos["road_trip_game"].tolist() == [0, 1, 2, 3, 0]
    assert bos["home_stand_game"].tolist() == [1, 0, 0, 0, 1]
    assert bos["first_home_after_trip"].tolist() == [0, 0, 0, 0, 1]
    assert bos["prev_trip_len"][4] == 3
    assert bos["travel_km_7d"][3] == bos["travel_km"][1:4].sum()
    assert bos["season_day"].tolist() == [0, 2, 3, 6, 8]

def test_neutral_site_home_game_counts_as_travel():
    feats = schedule_features(_games([(20251010, "PIT", "NSH"), (20251101, "NSH", "PIT")],
                                     venue=["PPG Paints Arena", "Avicii Arena"]))
    nsh = _team(feats, "NSH")
    assert nsh["home_stand_game"][1] == 0 and nsh["road_trip_game"][1] == 2
    assert nsh["travel_km"][1] == 5000                    # Europe leg is capped
    assert nsh["tz_shift"][1] == 3

def test_upcoming_games_get_features_and_preseason_ignored():
    games = _games([(20251001, "BOS", "TOR"), (20251010, "BOS", "TOR"), (20251011, "TOR", "BOS")])
    games.loc[0, "id"] = 2025010001
    feats = schedule_features(games)
    assert len(feats) == 4
    tor = _team(feats, "TOR")
    assert tor["back_to_back"].tolist() == [0, 1] and tor["travel_km"][0] > 600
