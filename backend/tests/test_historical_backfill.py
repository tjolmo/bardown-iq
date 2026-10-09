import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from app.schedules import is_regular_or_playoff_game, merge_season_schedules
from external.moneypuck.player import _normalize_tricodes
from external.nhl.response_models import GameResponse


def game(game_id, state="OFF", home="PHX", away="ATL"):
    return GameResponse(**{
        "id": game_id, "season": 20082009, "gameDate": "2009-04-11", "venue": {"default": "Arena"},
        "startTimeUTC": "2009-04-11T23:00:00Z", "gameState": state,
        "homeTeam": {"abbrev": home, "logo": "h.svg", "score": 3},
        "awayTeam": {"abbrev": away, "logo": "a.svg", "score": 2},
    })


def test_game_type_from_id():
    assert is_regular_or_playoff_game(2008020001)
    assert is_regular_or_playoff_game(2008030111)
    assert not is_regular_or_playoff_game(2008010001)  # preseason
    assert not is_regular_or_playoff_game(2008040001)  # all-star


def test_merge_dedupes_filters_and_marks_finished_off():
    home_schedule = [game(2008020002), game(2008010005, "FINAL"), game(2008030111, "FINAL")]
    away_schedule = [game(2008020002), game(2008020001)]
    merged = merge_season_schedules([home_schedule, None, away_schedule])
    assert [g.id for g in merged] == [2008020001, 2008020002, 2008030111]
    assert {g.game_state for g in merged} == {"OFF"}
    assert merged[0].home_score == 3 and merged[0].home_team_tri_code == "PHX"


def test_merge_keeps_unfinished_state():
    assert merge_season_schedules([[game(2026020001, "FUT")]])[0].game_state == "FUT"


def test_moneypuck_legacy_codes_by_season():
    df = pd.DataFrame({
        "season": [2013, 2013, 2014, 2010],
        "playerTeam": ["ARI", "S.J", "ARI", "ATL"],
        "opposingTeam": ["ATL", "ARI", "PHI", "ARI"],
    })
    out = _normalize_tricodes(df)
    assert out["playerTeam"].tolist() == ["PHX", "SJS", "ARI", "ATL"]
    assert out["opposingTeam"].tolist() == ["ATL", "PHX", "PHI", "PHX"]
