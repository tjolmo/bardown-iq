import datetime
import numpy as np
import pandas as pd
from predictions import features as F

NO_TEAM_CONTEXT = pd.DataFrame(columns=["game_id", "team"] + F.CONTEXT_TEAM_COLUMNS)

def _career(birth=datetime.date(1990, 1, 1)):
    """One forward's games over three seasons (two per season), plus a second, younger forward."""
    rows = []
    dates = [(2021, 20211015), (2021, 20220301), (2022, 20221015), (2022, 20230301), (2023, 20231015), (2023, 20240301)]
    for pid, born in ((1, birth), (2, datetime.date(2000, 6, 1))):
        for i, (season, date) in enumerate(dates):
            rows.append({"game_id": 1000 + 10 * i + pid, "player_id": pid, "season": season, "game_date": date,
                         "team": "AAA", "opponent": "BBB", "is_home": 1.0, "position": "C", "birth_date": born,
                         "goals": 1, "primary_assists": 1, "secondary_assists": 0, "points": 2, "x_goals": 0.5,
                         "toi": 3600.0, "shot_attempts": 3, "high_danger_shots": 1, "on_ice_x_goals_percentage": 0.5,
                         "game_score": 1.0 + i})
    return pd.DataFrame(rows)

def test_age_years():
    age = F.age_years(pd.Series(pd.to_datetime(["2020-07-01", "2020-01-01"])),
                      pd.Series([datetime.date(2000, 1, 1), None]))
    assert abs(age.iloc[0] - 20.5) < 0.01
    assert np.isnan(age.iloc[1])

def test_skater_age_features_cover_upcoming_rows():
    logs = _career()
    upcoming = pd.DataFrame([{"game_id": 9999, "player_id": 1, "season": 2024, "game_date": 20241010, "team": "AAA",
                              "opponent": "BBB", "is_home": 1.0, "position": "C"}])
    df, _ = F.skater_features(pd.concat([logs, upcoming], ignore_index=True), NO_TEAM_CONTEXT)
    row = df[df["game_id"] == 9999].iloc[0]
    expected = (pd.Timestamp("2024-10-10") - pd.Timestamp("1990-01-01")).days / 365.25
    assert abs(row["age"] - expected) < 1e-9 and abs(row["age_sq"] - expected ** 2) < 1e-6

def test_decayed_sums_use_only_prior_games():
    vals = pd.DataFrame({"x": [1.0, 1.0, 1.0, 5.0]})
    keys = pd.Series([1, 1, 1, 2])
    day = np.array([0.0, 365.0, 730.0, 730.0])
    prior = F._decayed_cumsum(vals, keys, day, 365.0, exclusive=True)["x"].to_numpy()
    np.testing.assert_allclose(prior, [0.0, 0.5, 0.75, 0.0])
    through = F._decayed_cumsum(vals, keys, day, 365.0)["x"].to_numpy()
    np.testing.assert_allclose(through, [1.0, 1.5, 1.75, 5.0])
    np.testing.assert_allclose(F._decayed_cumsum(vals, keys, day, None, exclusive=True)["x"], [0, 1, 2, 0])

def test_decayed_per60_rates_ignore_the_current_game():
    logs = _career()
    base, rates = F.skater_features(logs, NO_TEAM_CONTEXT, rate_half_life_days=365)
    changed_logs = logs.copy()
    last = changed_logs["game_date"] == 20240301
    changed_logs.loc[last, ["goals", "points"]] = 9
    changed, _ = F.skater_features(changed_logs, NO_TEAM_CONTEXT, league_rates=rates, rate_half_life_days=365)
    cols = [f"{s}_per60_shrunk" for s in F.SKATER_RATE_STATS]
    pd.testing.assert_frame_equal(base[cols], changed[cols])

def test_aging_ratings_use_only_earlier_games():
    logs = _career()
    before = F.skater_ratings(logs, age_mode="aging")
    changed = logs.copy()
    changed.loc[changed["season"] == 2023, "game_score"] = 50.0
    after = F.skater_ratings(changed, age_mode="aging")
    early = before["date"] < pd.Timestamp("2023-10-01")
    pd.testing.assert_frame_equal(before[early], after[early.to_numpy()])

def test_aging_curve_uses_completed_season_pairs():
    logs = _career().assign(is_defense=0.0)
    logs["_age_toi"] = F.age_years(F._date(logs["game_date"]), logs["birth_date"]) * logs["toi"]
    curve = F.aging_deltas(logs, ["game_score"], min_hours=1.0)
    # 2021 -> 2022 is the first pair; it may only inform seasons from 2023 on
    assert (curve.loc[curve["season"] <= 2022, "game_score"] == 0).all()
    assert (curve.loc[curve["season"] == 2023, "game_score"] != 0).any()

def test_player_landing_parses_birth_date():
    from external.nhl.response_models import PlayerLandingResponse
    p = PlayerLandingResponse(**{"playerId": 8478402, "headshot": None, "firstName": {"default": "Connor"},
                                 "lastName": {"default": "McDavid"}, "birthDate": "1997-01-13"})
    assert p.birth_date == datetime.date(1997, 1, 13)
    assert "birth_date" in p.model_dump()
