import json
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from external.espn import odds

FIXTURES = Path(__file__).parent / "fixtures" / "espn"


def load(name):
    with open(FIXTURES / name) as f:
        return json.load(f)


def by_provider(rows):
    return {r["provider"]: r for r in rows}


# --- team codes --------------------------------------------------------------

@pytest.mark.parametrize("espn,nhl", [
    ("NJ", "NJD"), ("SJ", "SJS"), ("TB", "TBL"), ("LA", "LAK"), ("UTAH", "UTA"),
    ("UTA", "UTA"), ("VGK", "VGK"), ("VEG", "VGK"), ("WSH", "WSH"), ("ARI", "ARI"),
    ("PHX", "ARI"), ("SEA", "SEA"), ("MTL", "MTL"), ("nj", "NJD"),
])
def test_team_code_mapping(espn, nhl):
    assert odds.to_nhl_code(espn) == nhl


@pytest.mark.parametrize("espn", [None, "", "TBD", "ATL", "TEAM-A"])
def test_unknown_team_codes_map_to_none(espn):
    assert odds.to_nhl_code(espn) is None


# --- odds math ---------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("+145", 145.0), ("-110", -110.0), (-185, -185.0), ("EVEN", 100.0),
    ("+0", None), (0, None), ("", None), (None, None), ("abc", None), ("-1.5", None),
])
def test_parse_american(raw, expected):
    assert odds.parse_american(raw) == expected


def test_devig_normalizes_to_one():
    home, away, overround = odds.devig(-130, 110)
    assert home + away == pytest.approx(1.0)
    assert overround == pytest.approx(130 / 230 + 100 / 210)
    assert home == pytest.approx((130 / 230) / overround)
    assert odds.devig(None, 110) == (None, None, None)


def test_three_way_prices_are_not_valid_two_way():
    assert odds.is_valid_two_way(-130, 110)
    assert odds.is_valid_two_way(-110, -110)
    assert not odds.is_valid_two_way(142, 155)    # regulation 3-way prices
    assert not odds.is_valid_two_way(-190, 400)   # 3-way, lopsided
    assert not odds.is_valid_two_way(145, 145)    # junk


# --- scoreboard --------------------------------------------------------------

def test_parse_scoreboard_keys_on_queried_local_date():
    events = odds.parse_scoreboard(load("scoreboard_20221115.json"), "20221115")
    assert len(events) == 4
    first = events[0]
    assert first["date"] == 20221115            # local date, not the UTC 2022-11-16
    assert first["start_utc"] == "2022-11-16T00:00Z"
    assert first["espn_event_id"] == "401458838"
    assert first["season_type"] == "regular"
    assert first["completed"] is True
    assert (first["home_team"], first["away_team"]) == ("BUF", "VAN")
    assert (first["home_score"], first["away_score"]) == (4, 5)
    mtl = next(e for e in events if e["home_team"] == "MTL")
    assert mtl["away_espn_abbr"] == "NJ" and mtl["away_team"] == "NJD"


def test_parse_scoreboard_empty_day():
    assert odds.parse_scoreboard({"events": []}, "20160715") == []
    assert odds.parse_scoreboard({}, "20160715") == []


# --- odds parsing ------------------------------------------------------------

def test_parse_odds_legacy_era_screens_three_way_rows():
    rows = by_provider(odds.parse_odds(load("odds_2019_legacy.json")))
    assert set(rows) == {"Bet365", "Caesars", "DraftKings", "Westgate", "CG Technology"}
    assert not rows["Bet365"]["valid_2way"]          # +145 / +145 junk
    assert not rows["DraftKings"]["valid_2way"]      # +142 / +155 regulation prices
    assert rows["DraftKings"]["home_prob"] is None
    caesars = rows["Caesars"]
    assert caesars["valid_2way"]
    assert (caesars["home_ml"], caesars["away_ml"]) == (-105.0, -110.0)
    assert caesars["home_prob"] + caesars["away_prob"] == pytest.approx(1.0)
    assert caesars["total"] == 6.5
    # no open/close snapshots in this era
    assert caesars["open_home_ml"] is None and caesars["close_home_ml"] is None


def test_parse_odds_espn_bet_era_open_close_and_live_feed():
    rows = by_provider(odds.parse_odds(load("odds_2025_espnbet.json")))
    bet = rows["ESPN BET"]
    assert not bet["is_live"] and rows["ESPN Bet - Live Odds"]["is_live"]
    assert (bet["home_ml"], bet["away_ml"]) == (155.0, -185.0)
    assert (bet["open_home_ml"], bet["open_away_ml"]) == (145.0, -170.0)
    assert (bet["close_home_ml"], bet["close_away_ml"]) == (155.0, -185.0)
    assert bet["total"] == 5.5
    assert bet["home_spread"] == 1.5


def test_parse_odds_draftkings_era():
    (dk,) = odds.parse_odds(load("odds_2026_draftkings.json"))
    assert dk["provider"] == "Draft Kings" and dk["provider_id"] == "100"
    assert (dk["home_ml"], dk["away_ml"]) == (-130.0, 110.0)
    assert (dk["open_home_ml"], dk["open_away_ml"]) == (-125.0, 105.0)
    assert dk["open_home_prob"] == pytest.approx(odds.devig(-125, 105)[0])
    assert dk["total"] == 6.5


def test_parse_odds_empty_pre_2019():
    assert odds.parse_odds(load("odds_2015_empty.json")) == []


# --- consensus ---------------------------------------------------------------

def test_consensus_median_of_valid_books_legacy():
    rows = odds.parse_odds(load("odds_2019_legacy.json"))
    c = odds.consensus(rows)
    valid = [r for r in rows if r["valid_2way"]]
    assert c["n_books"] == len(valid) == 3            # Caesars, CG Technology, Westgate
    assert c["n_books_total"] == 5
    assert "DraftKings" not in c["books"] and "Bet365" not in c["books"]
    expected = sorted(r["home_prob"] for r in valid)[1]
    assert c["home_prob_novig"] == pytest.approx(expected)
    assert c["home_prob_novig"] + c["away_prob_novig"] == pytest.approx(1.0)
    assert c["open_home_prob_novig"] is None


def test_consensus_excludes_live_odds():
    c = odds.consensus(odds.parse_odds(load("odds_2025_espnbet.json")))
    assert c["n_books"] == 1 and c["books"] == "ESPN BET"
    assert c["home_prob_novig"] == pytest.approx(odds.devig(155, -185)[0])
    assert c["total_line"] == 5.5                       # not the live 4.5
    assert c["open_home_prob_novig"] == pytest.approx(odds.devig(145, -170)[0])
    assert (c["open_home_ml"], c["open_away_ml"]) == (pytest.approx(145), pytest.approx(-170))


def _book(provider, home_ml, away_ml, open_home=None, open_away=None, live=False):
    hp, ap, ov = odds.devig(home_ml, away_ml)
    valid = odds.is_valid_two_way(home_ml, away_ml)
    return {"provider": provider, "is_live": live, "valid_2way": valid, "home_ml": home_ml, "away_ml": away_ml,
            "overround": ov, "home_prob": hp if valid else None, "away_prob": ap if valid else None,
            "total": 6.5, "open_home_ml": open_home, "open_away_ml": open_away,
            "open_home_prob": odds.devig(open_home, open_away)[0] if odds.is_valid_two_way(open_home, open_away) else None,
            "open_total": None}


def test_decimal_american_round_trip():
    for price in (-300, -150, -110, -100, 100, 105, 150, 320):
        assert odds.decimal_to_american(odds.american_to_decimal(price)) == pytest.approx(price if price != -100 else 100)
    assert odds.american_to_decimal(-2.5) is None and odds.american_to_decimal(0) is None


def _novig_from_prices(home_ml, away_ml):
    return odds.devig(home_ml, away_ml)[0]


def test_consensus_mixed_sign_books_regression():
    # pick'em game: books split across the +/-100 boundary. A plain median of American
    # odds gives (-105 + 105) / 2 = 0 and (-110 + 105) / 2 = -2.5 -- the corrupt values.
    rows = [_book("A", -105, -115), _book("B", 105, -125), _book("C", -110, -110), _book("D", 102, -122)]
    c = odds.consensus(rows)
    assert c["n_books"] == 4
    for price in (c["consensus_home_ml"], c["consensus_away_ml"]):
        assert abs(price) >= 100
    assert abs(_novig_from_prices(c["consensus_home_ml"], c["consensus_away_ml"]) - c["home_prob_novig"]) < 0.02
    # home decimals 1.909, 1.952, 2.02, 2.05 -> median (1.952 + 2.02) / 2 = 1.986 -> -101.4 (not ~0)
    assert c["consensus_home_ml"] == pytest.approx(-101.40, abs=0.01)


def test_consensus_two_books_straddling_even():
    c = odds.consensus([_book("A", -105, -115), _book("B", 105, -125)])
    assert c["consensus_home_ml"] == pytest.approx(100.12, abs=0.01)  # decimal mean of 1.952 and 2.05 = 2.001
    assert abs(_novig_from_prices(c["consensus_home_ml"], c["consensus_away_ml"]) - c["home_prob_novig"]) < 0.02


def test_consensus_opening_prices():
    rows = [_book("A", -150, 130, open_home=-105, open_away=-115),
            _book("B", -145, 125, open_home=105, open_away=-125),
            _book("C", -140, 120),                                    # no open snapshot
            _book("D", -150, 130, open_home=145, open_away=145),      # junk open pair -> ignored
            _book("Live", -400, 300, open_home=-300, open_away=250, live=True)]
    c = odds.consensus(rows)
    assert c["open_home_ml"] == pytest.approx(100.12, abs=0.01)
    assert abs(c["open_away_ml"]) >= 100
    assert c["open_home_prob_novig"] == pytest.approx(statistics.median([odds.devig(-105, -115)[0], odds.devig(105, -125)[0]]))
    assert abs(_novig_from_prices(c["open_home_ml"], c["open_away_ml"]) - c["open_home_prob_novig"]) < 0.02


def test_consensus_with_no_odds():
    c = odds.consensus([])
    assert c["n_books"] == 0 and c["home_prob_novig"] is None and c["total_line"] is None
    assert c["open_home_ml"] is None and c["open_away_ml"] is None


# --- NHL id matching ---------------------------------------------------------

def test_match_nhl_ids_exact_and_shifted_dates():
    nhl = [
        {"id": 2022020250, "date": 20221115, "home_team_tri_code": "BUF", "away_team_tri_code": "VAN"},
        {"id": 2022020251, "date": 20221116, "home_team_tri_code": "MTL", "away_team_tri_code": "NJD"},
    ]
    events = odds.parse_scoreboard(load("scoreboard_20221115.json"), "20221115")
    odds.match_nhl_ids(events, nhl)
    got = {e["espn_event_id"]: (e["nhl_game_id"], e["match_note"]) for e in events}
    assert got["401458838"] == ("2022020250", "exact")
    assert got["401458841"] == ("2022020251", "date+1")
    assert got["401458840"] == (None, "unmatched")


def test_match_nhl_ids_does_not_reuse_an_id():
    nhl = [{"id": 1, "date": 20230101, "home_team_tri_code": "BOS", "away_team_tri_code": "PIT"}]
    events = [
        {"date": 20230101, "home_team": "BOS", "away_team": "PIT"},
        {"date": 20230102, "home_team": "BOS", "away_team": "PIT"},
        {"date": 20230101, "home_team": None, "away_team": "PIT"},
    ]
    odds.match_nhl_ids(events, nhl)
    assert [e["nhl_game_id"] for e in events] == ["1", None, None]
    assert events[2]["match_note"] == "unknown_team"


def test_postponed_listing_does_not_steal_the_replayed_game():
    # 2021: FLA-DAL listed on 02-23 (postponed) and replayed 02-24 under a new event id
    nhl = [{"id": 7, "date": 20210224, "home_team_tri_code": "FLA", "away_team_tri_code": "DAL"}]
    events = [
        {"date": 20210223, "home_team": "FLA", "away_team": "DAL", "status": "STATUS_POSTPONED"},
        {"date": 20210225, "home_team": "FLA", "away_team": "DAL", "status": "STATUS_FINAL"},
        {"date": 20210224, "home_team": "FLA", "away_team": "DAL", "status": "STATUS_FINAL"},
    ]
    odds.match_nhl_ids(events, nhl)
    assert [(e["nhl_game_id"], e["match_note"]) for e in events] == [
        (None, "postponed"), (None, "unmatched"), ("7", "exact")]


@pytest.mark.parametrize("date,season", [
    (20151007, "20152016"), (20160415, "20152016"), (20200811, "20192020"),
    (20210113, "20202021"), (20210707, "20202021"), (20251007, "20252026"),
])
def test_season_label(date, season):
    assert odds.season_label(date) == season
