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


def test_skater_scrape_survives_one_bad_row(monkeypatch):
    cols = [
        'playerId', 'season', 'name', 'gameId', 'home_or_away',
        'playerTeam', 'opposingTeam', 'gameDate', 'situation',
        'I_F_goals', 'I_F_primaryAssists', 'I_F_secondaryAssists', 'I_F_points',
        'I_F_xGoals', 'icetime', 'I_F_highDangerShots',
        'I_F_shotAttempts', 'onIce_xGoalsPercentage', 'gameScore',
    ]
    good = [8478402, 2025, "Connor McDavid", 2025020001, "HOME", "EDM", "CGY", 20251008, "all",
            1, 1, 0, 2, 0.8, 1200, 2, 6, 0.55, 1.9]
    bad = list(good)
    bad[0] = "not an id"
    df = pd.DataFrame([good, bad, good], columns=cols)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("2025.csv", df.to_csv(index=False))
    buf.seek(0)
    monkeypatch.setattr(mp, "_download_season_zip", lambda url: buf)
    result = mp.scrape_all_skater_game_logs(2025)
    assert result is not None and len(result) == 2


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
