import io
import os
import sys
import zipfile

import pandas as pd
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from external.moneypuck import player as mp


class Row(BaseModel):
    a: int


def test_validate_rows_skips_only_bad_rows():
    rows = [{"a": 1}, {"a": "not a number"}, {"a": 3}]
    assert [r.a for r in mp._validate_rows(Row, rows, "test")] == [1, 3]


def test_validate_rows_all_valid():
    assert len(mp._validate_rows(Row, [{"a": 1}, {"a": 2}], "test")) == 2


SKATER_COLS = [
    'playerId', 'season', 'name', 'gameId', 'home_or_away',
    'playerTeam', 'opposingTeam', 'gameDate', 'situation',
    'I_F_goals', 'I_F_primaryAssists', 'I_F_secondaryAssists', 'I_F_points',
    'I_F_xGoals', 'icetime', 'I_F_highDangerShots',
    'I_F_shotAttempts', 'onIce_xGoalsPercentage', 'gameScore', 'I_F_shotsOnGoal',
]


def _skater_row(player_id=8478402, game_id=2025020001, situation="all", points=2, icetime=1200, sog=4,
                team="EDM", opp="CGY", season=2025):
    return [player_id, season, "Connor McDavid", game_id, "HOME", team, opp, 20251008, situation,
            1, 1, 0, points, 0.8, icetime, 2, 6, 0.55, 1.9, sog]


def _patch_skater_zip(monkeypatch, rows, season=2025):
    df = pd.DataFrame(rows, columns=SKATER_COLS)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{season}.csv", df.to_csv(index=False))
    buf.seek(0)
    monkeypatch.setattr(mp, "_download_season_zip", lambda url: buf)


def test_skater_scrape_survives_one_bad_row(monkeypatch):
    good = _skater_row()
    bad = list(good)
    bad[0] = "not an id"
    _patch_skater_zip(monkeypatch, [good, bad, good])
    result = mp.scrape_all_skater_game_logs(2025)
    assert result is not None and len(result) == 2


def test_skater_scrape_joins_power_play_and_sog(monkeypatch):
    rows = [
        _skater_row(player_id=1, game_id=10, situation="all", points=2, icetime=1200, sog=5),
        _skater_row(player_id=1, game_id=10, situation="5on4", points=1, icetime=180, sog=2),
        _skater_row(player_id=1, game_id=10, situation="5on5", points=1, icetime=900, sog=3),
        _skater_row(player_id=1, game_id=11, situation="all", points=0, icetime=1100, sog=1),
        _skater_row(player_id=1, game_id=11, situation="5on4", points=0, icetime=95.5, sog=0),
        # player 2 never on the power play -> 0s
        _skater_row(player_id=2, game_id=10, situation="all", points=1, icetime=800, sog=3),
        _skater_row(player_id=2, game_id=10, situation="4on5", points=0, icetime=120, sog=0),
    ]
    _patch_skater_zip(monkeypatch, rows)
    result = mp.scrape_all_skater_game_logs(2025)
    by_key = {(r.player_id, r.game_id): r for r in result}
    assert len(by_key) == 3 and len(result) == 3
    r = by_key[(1, 10)]
    assert (r.shots_on_goal, r.pp_toi, r.pp_points, r.toi, r.points) == (5, 180, 1, 1200, 2)
    r = by_key[(1, 11)]
    assert (r.shots_on_goal, r.pp_toi, r.pp_points) == (1, 95.5, 0)
    r = by_key[(2, 10)]
    assert (r.shots_on_goal, r.pp_toi, r.pp_points) == (3, 0, 0)


def test_skater_scrape_keeps_legacy_tricodes_with_pp_join(monkeypatch):
    rows = [
        _skater_row(player_id=1, game_id=10, team="ARI", opp="T.B", season=2012),
        _skater_row(player_id=1, game_id=10, situation="5on4", team="ARI", opp="T.B", season=2012),
    ]
    _patch_skater_zip(monkeypatch, rows, season=2012)
    (r,) = mp.scrape_all_skater_game_logs(2012)
    assert (r.player_team_tricode, r.opposing_team_tricode) == ("PHX", "TBL")
    assert r.pp_toi == 1200


def test_skater_response_new_fields_optional():
    from external.moneypuck.response_models import SkaterGameLogResponse
    row = dict(zip(SKATER_COLS[:-1], _skater_row()[:-1]))
    r = SkaterGameLogResponse.model_validate(row)
    assert r.shots_on_goal is None and r.pp_toi is None and r.pp_points is None
    r = SkaterGameLogResponse.model_validate({**row, "I_F_shotsOnGoal": float("nan")})
    assert r.shots_on_goal is None


def _zip_with(*names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in names:
            z.writestr(name, "a\n1\n")
    buf.seek(0)
    return zipfile.ZipFile(buf)


def test_season_csv_member_flat_and_nested():
    assert mp._season_csv_member(_zip_with("2025.csv"), 2025) == "2025.csv"
    nested = "my stuff/var/www/html/moneypuck/summaryData/seasonPlayersSummary/skaters/2024.csv"
    assert mp._season_csv_member(_zip_with(nested, "readme.txt"), 2024) == nested


def test_season_csv_member_falls_back_to_only_csv():
    assert mp._season_csv_member(_zip_with("other.csv"), 2024) == "other.csv"


def test_season_csv_member_ambiguous_raises():
    import pytest
    with pytest.raises(ValueError):
        mp._season_csv_member(_zip_with("a.csv", "b.csv"), 2024)
    with pytest.raises(ValueError):
        mp._season_csv_member(_zip_with("readme.txt"), 2024)


def test_goalie_scrape_reads_nested_csv(monkeypatch):
    cols = [
        'playerId', 'season', 'name', 'gameId', 'home_or_away',
        'playerTeam', 'opposingTeam', 'gameDate',
        "situation", "icetime", "xGoals", "goals",
        "unblocked_shot_attempts", "xRebounds", "rebounds",
        "xFreeze", "freeze", "xOnGoal", "ongoal", "xPlayStopped",
        "playStopped", "xPlayContinuedInZone", "xPlayContinuedOutsideZone", "flurryAdjustedxGoals",
        "lowDangerShots", "mediumDangerShots", "highDangerShots", "lowDangerxGoals",
        "mediumDangerxGoals", "highDangerxGoals", "blocked_shot_attempts",
        "penalityMinutes", "penalties",
    ]
    row = [8471679, 2021, "Some Goalie", 2021020001, "HOME", "T.B", "PIT", 20211012, "all"] + [1] * 24
    df = pd.DataFrame([row, row[:8] + ["5on5"] + row[9:]], columns=cols)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("my stuff/var/www/html/moneypuck/summaryData/seasonPlayersSummary/goalies/2021.csv",
                   df.to_csv(index=False))
    buf.seek(0)
    monkeypatch.setattr(mp, "_download_season_zip", lambda url: buf)
    result = mp.scrape_all_goalie_game_logs(2021)
    assert result is not None and len(result) == 1
