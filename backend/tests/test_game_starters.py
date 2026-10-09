"""Starting goalies: NHL gamecenter + ESPN probables parsing (saved JSON fixtures, no network) and how known
starters flow into the features."""
import datetime
import json
from pathlib import Path

import pandas as pd

from external.espn.starters import match_goalie, parse_probable_goalies, resolve_starters
from external.nhl.games import parse_actual_starters, parse_boxscore_starters, parse_game_goalies, parse_pbp_starters
from predictions import features as F
from predictions.predict import goalie_start_info

FIX = Path(__file__).parent / "fixtures"


def _load(*parts):
    return json.loads((FIX.joinpath(*parts)).read_text())


def _pregame_goalies():
    return parse_game_goalies(_load("nhl", "landing_2026020053_pregame.json"), _load("nhl", "pbp_2026020053_pregame.json"))


def test_espn_expected_goalies_are_probable_announced_are_confirmed():
    picks = parse_probable_goalies(_load("espn", "scoreboard_starters_20261007.json"))
    assert len(picks) == 6
    # EDM had already announced Levi the night before; the rest are ESPN's expected starters
    assert {p["team"]: p["status"] for p in picks if p["status"] == "confirmed"} == {"EDM": "confirmed"}
    assert sum(p["status"] == "probable" for p in picks) == 5
    wsh = next(p for p in picks if p["team"] == "WSH")
    assert (wsh["home"], wsh["away"], wsh["full_name"], wsh["jersey"]) == ("WSH", "PIT", "Logan Thompson", 48)
    assert wsh["start"] == datetime.datetime(2026, 10, 7, 23, 30, tzinfo=datetime.timezone.utc)


def test_espn_confirmed_goalies_and_team_codes():
    picks = parse_probable_goalies(_load("espn", "scoreboard_starters_20261006.json"))
    assert {p["status"] for p in picks} == {"confirmed"}
    assert {"LAK", "FLA", "NJD"} <= {p["team"] for p in picks}    # ESPN "LA", "NJ" mapped to NHL codes


def test_pregame_landing_lists_rostered_goalies_without_dressed_flag():
    goalies = _pregame_goalies()
    assert {(g.team, g.player_id) for g in goalies} == {
        ("WSH", 8479292), ("WSH", 8480313), ("PIT", 8483703), ("PIT", 8481668)}
    assert all(g.dressed is None for g in goalies)     # rosterSpots are empty this far before puck drop


def test_roster_spots_mark_dressed_goalies_and_add_call_ups():
    landing = _load("nhl", "landing_2026020053_pregame.json")
    pbp = _load("nhl", "pbp_2026020053_pregame.json")
    wsh, pit = pbp["homeTeam"]["id"], pbp["awayTeam"]["id"]
    pbp["rosterSpots"] = [
        {"teamId": wsh, "playerId": 8480313, "positionCode": "G", "lastName": {"default": "Thompson"}, "sweaterNumber": 48},
        {"teamId": wsh, "playerId": 8479292, "positionCode": "G", "lastName": {"default": "Lindgren"}, "sweaterNumber": 79},
        {"teamId": pit, "playerId": 8481668, "positionCode": "G", "lastName": {"default": "Silovs"}, "sweaterNumber": 37},
        {"teamId": pit, "playerId": 9999999, "positionCode": "G", "lastName": {"default": "Callup"}, "sweaterNumber": 30},
    ]
    by_id = {g.player_id: g for g in parse_game_goalies(landing, pbp)}
    assert by_id[8480313].dressed and by_id[8481668].dressed and by_id[9999999].dressed
    assert by_id[8483703].dressed is False          # Murashov not dressed


def test_play_by_play_gives_the_goalie_in_net_after_puck_drop():
    assert parse_pbp_starters(_load("nhl", "pbp_2026020052_final.json")) == {"LAK": 8475311, "FLA": 8474593}
    assert parse_pbp_starters(_load("nhl", "pbp_2026020053_pregame.json")) == {}


def test_pulled_starter_is_still_the_starter_2008():
    # LAK's Quick was pulled after 7:41 (Ersberg played 55:36): both the boxscore flag and the first shot faced name
    # Quick; the goalie with the most ice time would name the reliever. 2008-09 pbp has goalieInNetId on shots too.
    box, pbp = _load("nhl", "boxscore_2008020846_final.json"), _load("nhl", "pbp_2008020846_final.json")
    assert parse_boxscore_starters(box) == {"LAK": 8471734, "ATL": 8460704}
    assert parse_pbp_starters(pbp) == {"LAK": 8471734, "ATL": 8460704}
    starters, method, disagree = parse_actual_starters(box, pbp)
    assert starters == {"LAK": 8471734, "ATL": 8460704} and set(method.values()) == {"pbp"} and not disagree


def test_actual_starters_disagreements_and_fallbacks():
    box, pbp = _load("nhl", "boxscore_2008020846_final.json"), _load("nhl", "pbp_2008020846_final.json")
    lak, atl = box["playerByGameStats"]["homeTeam"]["goalies"], box["playerByGameStats"]["awayTeam"]["goalies"]
    # the flag on the reliever of a starter who faced shots: the play-by-play wins
    for g in lak:
        g["starter"] = g["playerId"] == 8473975
    starters, method, disagree = parse_actual_starters(box, pbp)
    assert starters["LAK"] == 8471734 and method["LAK"] == "pbp" and disagree == {"LAK": (8473975, 8471734)}
    # a flagged starter who played but faced no shot (hurt before the first one): the flag wins
    for g in lak:
        g["starter"], g["shotsAgainst"] = g["playerId"] == 8473975, 0 if g["playerId"] == 8473975 else g["shotsAgainst"]
    starters, method, _ = parse_actual_starters(box, pbp)
    assert starters["LAK"] == 8473975 and method["LAK"] == "boxscore"
    # no play-by-play: the flag; no boxscore: the play-by-play
    assert parse_actual_starters(box, None)[0] == {"LAK": 8473975, "ATL": 8460704}
    assert parse_actual_starters(None, pbp)[0] == {"LAK": 8471734, "ATL": 8460704}
    assert parse_actual_starters(None, None) == ({}, {}, {})
    assert atl  # ATL untouched: flag and play-by-play agree


def test_play_by_play_skips_empty_net_and_shootout_shots():
    pbp = {"homeTeam": {"id": 1, "abbrev": "AAA"}, "awayTeam": {"id": 2, "abbrev": "BBB"}, "plays": [
        # empty-net goal by AAA (no goalie in net), then BBB's shootout attempt on AAA's goalie
        {"sortOrder": 1, "typeDescKey": "goal", "periodDescriptor": {"periodType": "REG"}, "details": {"eventOwnerTeamId": 1}},
        {"sortOrder": 2, "typeDescKey": "shot-on-goal", "periodDescriptor": {"periodType": "SO"},
         "details": {"eventOwnerTeamId": 2, "goalieInNetId": 11}},
        {"sortOrder": 3, "typeDescKey": "missed-shot", "periodDescriptor": {"periodType": "REG"},
         "details": {"eventOwnerTeamId": 1, "goalieInNetId": 22}},
    ]}
    assert parse_pbp_starters(pbp) == {"BBB": 22}


def test_espn_pick_matched_to_nhl_ids():
    picks = parse_probable_goalies(_load("espn", "scoreboard_starters_20261007.json"))
    found, problems = resolve_starters(2026020053, "WSH", "PIT", picks, _pregame_goalies(), {})
    assert not problems
    assert {(s.team, s.player_id, s.status, s.source) for s in found} == {
        ("WSH", 8480313, "probable", "espn"), ("PIT", 8481668, "probable", "espn")}


def test_match_goalie_last_name_and_jersey_fallbacks():
    goalies = _pregame_goalies()
    assert match_goalie({"team": "PIT", "full_name": "Artūrs Šilovs", "jersey": 37}, goalies).player_id == 8481668
    assert match_goalie({"team": "PIT", "full_name": None, "jersey": 1}, goalies).player_id == 8483703
    assert match_goalie({"team": "PIT", "full_name": "Logan Thompson", "jersey": 48}, goalies) is None   # wrong team


def test_undressed_espn_goalie_dropped_and_pbp_beats_espn():
    picks = parse_probable_goalies(_load("espn", "scoreboard_starters_20261007.json"))
    goalies = [g.model_copy(update={"dressed": g.player_id != 8480313}) if g.team == "WSH" else g for g in _pregame_goalies()]
    found, problems = resolve_starters(2026020053, "WSH", "PIT", picks, goalies, {"PIT": 8483703})
    assert [(s.team, s.player_id, s.status, s.source) for s in found] == [("PIT", 8483703, "actual", "nhl")]
    assert len(problems) == 1 and "not dressed" in problems[0]


# ---------- features ----------

def _team_games():
    dates = [20251001, 20251003, 20251005, 20251007]
    return pd.DataFrame({"game_id": [1, 2, 3, 4], "team": "AAA",
                         "date": pd.to_datetime([str(d) for d in dates], format="%Y%m%d")})


def _goalies():
    # A starts games 1 and 3, B starts game 2 (A relieved there); game 4 is upcoming
    rows = [(1, 10, 3600, 2.0, 1), (2, 20, 2400, 3.0, 4), (2, 10, 1200, 1.0, 2), (3, 10, 3600, 2.5, 2)]
    df = pd.DataFrame(rows, columns=["game_id", "player_id", "toi", "x_goals_against", "goals_against"])
    df["team"] = "AAA"
    df["game_date"] = df["game_id"].map({1: 20251001, 2: 20251003, 3: 20251005})
    return df


def _actual(*rows):
    return pd.DataFrame(rows, columns=["game_id", "team", "player_id"]).assign(status="actual", source="nhl")


def test_starter_picks_actual_for_played_known_for_upcoming():
    # B (20) is the stored actual starter of game 2; A relieved him
    known = pd.concat([_actual((1, "AAA", 10), (2, "AAA", 20), (3, "AAA", 10)),
                       pd.DataFrame({"game_id": [4], "team": ["AAA"], "player_id": [20], "status": ["confirmed"]})])
    picks = F.starter_picks(_team_games(), _goalies(), known, prefer_actual=True).set_index("game_id")
    assert picks.loc[2, "player_id"] == 20 and picks.loc[2, "status"] == "actual"
    assert picks.loc[4, "player_id"] == 20 and picks.loc[4, "status"] == "confirmed"
    # without a known starter the upcoming game falls back to the projection (A: most starts recently)
    picks = F.starter_picks(_team_games(), _goalies(), None, prefer_actual=True).set_index("game_id")
    assert picks.loc[4, "player_id"] == 10 and picks.loc[4, "status"] == "projected"
    # played games without a stored actual starter keep the projection (never the most-ice-time goalie)
    assert (picks["status"] == "projected").all()


def test_pulled_starter_counts_as_starter():
    goalies = _goalies()
    # game 2: A (10) started and was pulled after 20 minutes, B (20) played 40
    goalies.loc[goalies["game_id"] == 2, "toi"] = goalies.loc[goalies["game_id"] == 2, "player_id"].map({20: 2400, 10: 1200})
    known = _actual((1, "AAA", 10), (2, "AAA", 10), (3, "AAA", 10))
    assert F.most_ice_time(goalies).set_index("game_id").loc[2, "player_id"] == 20
    assert F.actual_starters(goalies, known).set_index("game_id").loc[2, "player_id"] == 10
    mask = F.starter_rows(goalies, known)
    assert goalies[mask][["game_id", "player_id"]].values.tolist() == [[1, 10], [2, 10], [3, 10]]
    # no stored starters: the most-ice-time goalie, as before
    assert goalies[F.starter_rows(goalies)][["game_id", "player_id"]].values.tolist() == [[1, 10], [2, 20], [3, 10]]


def test_projection_learns_from_actual_starters():
    tg = pd.DataFrame({"game_id": range(1, 6), "team": "AAA",
                       "date": pd.to_datetime(["20251001", "20251003", "20251005", "20251007", "20251009"])})
    # B (20) is pulled in games 1-3 and A (10) plays most of them; B started all three
    rows = [(g, p, toi, 1.0, 1) for g in (1, 2, 3) for p, toi in ((20, 900), (10, 2700))]
    goalies = pd.DataFrame(rows, columns=["game_id", "player_id", "toi", "x_goals_against", "goals_against"]).assign(team="AAA")
    goalies["game_date"] = goalies["game_id"].map({1: 20251001, 2: 20251003, 3: 20251005})
    proj = lambda known: F.starter_picks(tg, goalies, known).set_index("game_id").loc[4, "player_id"]
    assert proj(None) == 10
    assert proj(_actual((1, "AAA", 20), (2, "AAA", 20), (3, "AAA", 20))) == 20


def test_projected_statuses_ignored_and_default_unchanged():
    known = pd.DataFrame({"game_id": [4], "team": ["AAA"], "player_id": [20], "status": ["projected"]})
    picks = F.starter_picks(_team_games(), _goalies(), known).set_index("game_id")
    assert picks.loc[4, "player_id"] == 10
    # default (experiments): projection for every game, played or not
    assert (F.starter_picks(_team_games(), _goalies())["status"] == "projected").all()


def test_starter_features_use_the_known_starter_quality():
    known = pd.DataFrame({"game_id": [4], "team": ["AAA"], "player_id": [20], "status": ["probable"]})
    feats = F.starter_features(_team_games(), _goalies(), known, prefer_actual=True).set_index("game_id")
    gsax_b = (3.0 - 4) / (2400 / 3600 + F.GOALIE_PRIOR_HOURS)
    assert abs(feats.loc[4, "starter_gsax60"] - gsax_b) < 1e-9


def test_goalie_start_info():
    picks = pd.DataFrame({"game_id": [4], "team": ["AAA"], "player_id": [20], "status": ["confirmed"]}).set_index(["game_id", "team"])
    assert goalie_start_info(picks, 4, "AAA", 20) == {"starting": True, "starter_status": "confirmed"}
    assert goalie_start_info(picks, 4, "AAA", 10) == {"starting": False, "starter_status": "confirmed"}
    assert goalie_start_info(picks, 5, "AAA", 10) == {"starting": None, "starter_status": None}
    assert goalie_start_info(None, 4, "AAA", 10) == {"starting": None, "starter_status": None}
