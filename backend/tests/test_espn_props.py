import json
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.dialects import postgresql

from app.crud.player_prop_odds import dedupe_prop_rows, player_prop_odds_upsert_stmt
from external.espn.odds import match_nhl_ids
from external.espn.player_ids import build_player_index, resolve_athlete, resolve_athletes
from external.espn.props import (
    assign_unlabelled_sides, athlete_contexts, build_markets, build_player_prop_rows, parse_athlete,
    parse_prop_bets, parse_prop_rows, prop_providers,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "espn")


def load(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


def by_key(markets):
    return {(m["espn_athlete_id"], m["prop_type"], m["line"]): m for m in markets}


# ---------------------------------------------------------------------------
# provider discovery
# ---------------------------------------------------------------------------

def test_prop_providers_skips_live_feed_and_books_without_props():
    payload = {"items": [
        {"provider": {"id": "58", "name": "ESPN BET"}, "propBets": {"$ref": ".../odds/58/propBets"}},
        {"provider": {"id": "59", "name": "ESPN Bet - Live Odds"}, "propBets": {"$ref": ".../odds/59/propBets"}},
        {"provider": {"id": "100", "name": "Draft Kings"}},
    ]}
    assert prop_providers(payload) == [("58", "ESPN BET")]
    assert prop_providers(None) == []


# ---------------------------------------------------------------------------
# ESPN BET era: labelled over/under
# ---------------------------------------------------------------------------

def test_espnbet_labelled_pairs_and_one_sided_markets():
    markets = by_key(parse_prop_bets(load("props_2024_espnbet.json")))
    points = markets[(3822, "points", 0.5)]
    assert (points["over_price"], points["under_price"]) == (110, -140)
    assert (points["open_line"], points["open_over_price"], points["open_under_price"]) == (0.5, 110, -140)
    assert points["sides_inferred"] is False
    goals = markets[(3822, "goals", 0.5)]
    assert (goals["over_price"], goals["under_price"]) == (320, -550)
    first = markets[(3822, "first_goal", 0.5)]
    assert (first["over_price"], first["under_price"]) == (1500, None)
    two_plus = markets[(5517, "goals_milestone", 1.5)]
    assert two_plus["over_price"] == 2500 and two_plus["under_price"] is None
    # "Even" is +100; open differs from current
    blocks = markets[(2562610, "blocked_shots", 1.5)]
    assert (blocks["over_price"], blocks["under_price"], blocks["open_over_price"], blocks["open_under_price"]) == (100, -130, -105, -128)
    # no team/game props and no ambiguous "Hockey Player Prop" rows
    assert {m["prop_type"] for m in markets.values()} <= {"points", "goals", "first_goal", "goals_milestone", "blocked_shots", "hits"}


def test_espnbet_under_listed_first_and_open_on_a_different_line():
    hits = by_key(parse_prop_bets(load("props_2024_espnbet.json")))[(2554903, "hits", 1.5)]
    # under row comes first in the payload; labels, not order, decide
    assert (hits["over_price"], hits["under_price"]) == (-200, 140)
    # opened at 2.5: kept as its own line, never merged into the 1.5 market's prices
    assert hits["open_line"] == 2.5
    assert (hits["open_over_price"], hits["open_under_price"]) == (135, -185)


# ---------------------------------------------------------------------------
# DraftKings era: unlabelled rows
# ---------------------------------------------------------------------------

def test_draftkings_pairs_are_over_then_under():
    markets = by_key(parse_prop_bets(load("props_2026_draftkings.json")))
    points = markets[(2593315, "points", 0.5)]
    assert (points["over_price"], points["under_price"]) == (-120, -110)
    assert (points["open_over_price"], points["open_under_price"]) == (-110, -120)
    assert points["sides_inferred"] is True
    sog = markets[(2593315, "shots_on_goal", 1.5)]
    assert (sog["over_price"], sog["under_price"]) == (-168, 130)
    # the "1+" points ladder is the same event as over 0.5 and prices close to the first row
    ladder = markets[(2593315, "points_milestone", 0.5)]
    assert ladder["over_price"] == -115 and ladder["under_price"] is None
    anytime = markets[(2593315, "anytime_goal", 0.5)]
    assert (anytime["over_price"], anytime["under_price"]) == (275, None)


def test_draftkings_line_moved_keeps_open_line_separate():
    sog = by_key(parse_prop_bets(load("props_2026_draftkings.json")))[(4024988, "shots_on_goal", 3.5)]
    assert (sog["over_price"], sog["under_price"]) == (140, -182)
    assert (sog["open_line"], sog["open_over_price"], sog["open_under_price"]) == (2.5, -162, 126)
    ladder = by_key(parse_prop_bets(load("props_2026_draftkings.json")))[(2593315, "shots_on_goal_milestone", 2.5)]
    # ladder rung 3+ opened as 2+
    assert (ladder["over_price"], ladder["open_line"], ladder["open_over_price"]) == (170, 1.5, -160)


def test_draftkings_duplicate_two_plus_goal_markets_collapse():
    markets = [m for m in parse_prop_bets(load("props_2026_draftkings.json")) if m["espn_athlete_id"] == 2562602]
    assert len(markets) == 1 and markets[0]["prop_type"] == "goals_milestone" and markets[0]["line"] == 1.5


def test_draftkings_skips_team_props_and_handles_saves():
    markets = parse_prop_bets(load("props_2026_draftkings.json"))
    assert all(m["espn_athlete_id"] for m in markets)
    saves = by_key(markets)[(4736758, "saves", 23.5)]
    assert (saves["over_price"], saves["under_price"]) == (-115, -115)


def test_unpaired_unlabelled_row_is_dropped():
    rows = [
        {"idx": 0, "espn_athlete_id": 1, "espn_type": "Total Points", "prop_type": "points", "kind": "ou",
         "price": 150.0, "open_price": 150.0, "target": 0.5, "open_target": 0.5, "side": None, "open_side": None, "last_updated": None},
        {"idx": 1, "espn_athlete_id": 1, "espn_type": "Total Points", "prop_type": "points", "kind": "ou",
         "price": -200.0, "open_price": -200.0, "target": 0.5, "open_target": 0.5, "side": None, "open_side": None, "last_updated": None},
        {"idx": 2, "espn_athlete_id": 2, "espn_type": "Total Points", "prop_type": "points", "kind": "ou",
         "price": 150.0, "open_price": 150.0, "target": 0.5, "open_target": 0.5, "side": None, "open_side": None, "last_updated": None},
    ]
    assign_unlabelled_sides(rows)
    assert [r["side"] for r in rows] == ["over", "under", None]
    markets = build_markets(rows)
    assert [(m["espn_athlete_id"], m["over_price"], m["under_price"]) for m in markets] == [(1, 150, -200)]


def test_parse_prop_rows_reads_targets_and_athletes():
    rows = parse_prop_rows(load("props_2026_draftkings.json"))
    ladder = next(r for r in rows if r["espn_type"] == "Points Milestones")
    assert ladder["target"] == 1.0 and ladder["kind"] == "milestone"
    assert all(isinstance(r["espn_athlete_id"], int) for r in rows)


# ---------------------------------------------------------------------------
# athlete matching
# ---------------------------------------------------------------------------

PLAYERS = [
    {"id": 1, "first_name": "Elias", "last_name": "Pettersson", "position": "C", "current_team": "VAN"},
    {"id": 2, "first_name": "Elias", "last_name": "Pettersson", "position": "D", "current_team": "VAN"},
    {"id": 3, "first_name": "Alexander", "last_name": "Nylander", "position": "R", "current_team": "CBJ"},
    {"id": 4, "first_name": "Alex", "last_name": "Tuch", "position": "R", "current_team": "BUF"},
    {"id": 5, "first_name": "Tim", "last_name": "Stützle", "position": "C", "current_team": "OTT"},
    {"id": 6, "first_name": "Sebastian", "last_name": "Aho", "position": "C", "current_team": "CAR"},
    {"id": 7, "first_name": "Sebastian", "last_name": "Aho", "position": "D", "current_team": "PIT"},
    {"id": 8, "first_name": "Jake", "last_name": "Allen", "position": "G", "current_team": "NJD"},
    {"id": 9, "first_name": "Retired", "last_name": "Guy", "position": "C", "current_team": None},
]
TEAM_SEASONS = {(1, 2024, "VAN"), (2, 2024, "VAN"), (3, 2024, "PIT"), (4, 2024, "BUF"), (5, 2024, "OTT"),
                (6, 2024, "CAR"), (7, 2024, "NYI"), (8, 2024, "MTL")}
GAME_PLAYERS = {(2024020001, 1), (2024020001, 2)}
IDX = build_player_index(PLAYERS, TEAM_SEASONS, GAME_PLAYERS)
VAN_GAME = [(2024020001, "VAN", "EDM")]


def athlete(first, last, pos="C"):
    return {"first_name": first, "last_name": last, "full_name": f"{first} {last}", "position": pos}


def test_exact_name_with_accents_and_team_evidence():
    assert resolve_athlete(IDX, athlete("Tim", "Stutzle"), [(2024020002, "OTT", "TOR")]) == (5, "exact")


def test_namesakes_separated_by_position_and_team():
    # ESPN says D -> the defenceman, even though both played in the game
    assert resolve_athlete(IDX, athlete("Elias", "Pettersson", "D"), VAN_GAME) == (2, "exact")
    # two skaters named Sebastian Aho: the Carolina one is on the ice for CAR games
    assert resolve_athlete(IDX, athlete("Sebastian", "Aho", "C"), [(2024020003, "CAR", "BOS")]) == (6, "exact")
    assert resolve_athlete(IDX, athlete("Sebastian", "Aho", "D"), [(2024020004, "NYI", "BOS")]) == (7, "exact")


def test_both_namesakes_with_identical_evidence_is_ambiguous():
    idx = build_player_index([dict(p, position="C") for p in PLAYERS[:2]], TEAM_SEASONS, GAME_PLAYERS)
    assert resolve_athlete(idx, athlete("Elias", "Pettersson", "C"), VAN_GAME) == (None, "exact_ambiguous")


def test_loose_first_name_match_needs_team_evidence():
    assert resolve_athlete(IDX, athlete("Alex", "Nylander", "RW"), [(2024020005, "PIT", "WSH")]) == (3, "loose")
    assert resolve_athlete(IDX, athlete("Alex", "Nylander", "RW"), [(2024020005, "DAL", "WSH")]) == (None, "loose_no_team_evidence")


def test_goalie_vs_skater_and_unknown_names():
    assert resolve_athlete(IDX, athlete("Jake", "Allen", "G"), [(2024020006, "MTL", "BOS")]) == (8, "exact")
    assert resolve_athlete(IDX, athlete("Jake", "Allen", "C"), [(2024020006, "MTL", "BOS")]) == (None, "name_not_found")
    assert resolve_athlete(IDX, athlete("Nobody", "Here"), VAN_GAME) == (None, "name_not_found")
    # unique name but never played for either team -> rejected
    assert resolve_athlete(IDX, athlete("Retired", "Guy"), VAN_GAME) == (None, "exact_no_team_evidence")
    # playoff-only call-up: no log for the team that season, but one the season before
    assert resolve_athlete(IDX, athlete("Jake", "Allen", "G"), [(2025030111, "MTL", "WSH")]) == (8, "exact")
    assert resolve_athlete(IDX, athlete("Jake", "Allen", "G"), [(2026020001, "BOS", "WSH")]) == (None, "exact_no_team_evidence")


def test_resolve_athletes_uses_known_mapping_and_goalie_hint():
    athletes = {10: athlete("Jake", "Allen", None), 11: athlete("Alex", "Tuch", "RW")}
    mapping, unmatched = resolve_athletes(IDX, athletes, {10: [(2024020006, "MTL", "BOS")], 11: [(2024020007, "BUF", "OTT")], 12: VAN_GAME},
                                          goalie_hints={10: True}, known={12: 1})
    assert mapping == {10: 8, 11: 4, 12: 1} and unmatched == {}


def test_parse_athlete_bio():
    info = parse_athlete(load("athlete_3114766.json"))
    assert info["full_name"] == "Alex Tuch" and info["position"] == "RW" and info["birth_date"] == "1996-05-10"
    assert parse_athlete({"count": 0, "items": [], "_status": 404}) is None


# ---------------------------------------------------------------------------
# rows for the table
# ---------------------------------------------------------------------------

def test_build_player_prop_rows_matches_games_and_players():
    games = [{"id": 2025020700, "date": 20260115, "home_team_tri_code": "BUF", "away_team_tri_code": "PHI"}]
    events = [
        {"espn_event_id": "401803091", "date": 20260115, "home_team": "BUF", "away_team": "PHI", "status": "STATUS_FINAL", "completed": True},
        {"espn_event_id": "999", "date": 20260115, "home_team": "NYR", "away_team": "NJD", "status": "STATUS_FINAL", "completed": True},
    ]
    markets = [dict(m, book="Draft Kings") for m in parse_prop_bets(load("props_2026_draftkings.json"))]
    by_event = {"401803091": markets, "999": markets[:1]}
    match_nhl_ids(events, games)
    contexts, hints = athlete_contexts(events, by_event, games)
    assert contexts[2593315] == [(2025020700, "BUF", "PHI")] and hints[4736758] is True and hints[2593315] is False
    rows, stats = build_player_prop_rows(events, by_event, games, {2593315: 44})
    assert {r["player_id"] for r in rows} == {44} and all(r["game_id"] == 2025020700 for r in rows)
    assert stats["markets_unmatched_game"] == 1 and stats["markets_unmatched_player"] == len(markets) - len(rows)
    points = next(r for r in rows if r["prop_type"] == "points")
    assert points["espn_event_id"] == 401803091 and points["book"] == "Draft Kings" and points["sides_inferred"]


def test_upsert_statement_keeps_stored_open_prices():
    row = {"game_id": 1, "player_id": 2, "prop_type": "points", "line": 0.5, "book": "ESPN BET", "espn_athlete_id": 3,
           "over_price": 110, "under_price": -140, "open_line": None, "open_over_price": None, "open_under_price": None,
           "sides_inferred": False, "espn_last_updated": None, "espn_event_id": 5}
    assert len(dedupe_prop_rows([row, dict(row, over_price=120)])) == 1
    sql = str(player_prop_odds_upsert_stmt([row]).compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (game_id, player_id, prop_type, line, book) DO UPDATE" in sql
    assert "coalesce(excluded.open_over_price, player_prop_odds.open_over_price)" in sql
