"""Injury report: ESPN parsing (saved JSON fixture, no network), athlete matching, which listings take a player out
of which games, and how that flows into expected lineups, roster ratings, teammate quality and the prediction log."""
import asyncio
import datetime
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.crud.player_injuries import insert_injury_snapshot, load_injury_report
from app.models import Base
from external.espn.injuries import match_injured_player, normalize_status, parse_injuries
from external.espn.player_ids import build_player_index
from predictions import features as F
from predictions import predict as P

FIX = Path(__file__).parent / "fixtures"
UTC = datetime.timezone.utc


def _report():
    return parse_injuries(json.loads((FIX / "espn" / "injuries_20261007.json").read_text()))


# ---------- parsing ----------

def test_parse_league_injury_report():
    rows = _report()
    assert len(rows) == 31
    by_name = {r["full_name"]: r for r in rows}
    helleson = by_name["Drew Helleson"]
    assert helleson["espn_athlete_id"] == 4565270          # only in the athlete's links
    assert (helleson["team"], helleson["position"], helleson["status"]) == ("ANA", "D", "ir")
    assert helleson["report_date"] == datetime.datetime(2026, 10, 7, 18, 11, tzinfo=UTC)
    assert helleson["return_date"] == datetime.date(2026, 10, 10)
    assert helleson["espn_injury_id"] == 595032 and helleson["fantasy_status"] == "IR"
    statuses = {name: by_name[name]["status"] for name in
                ("Troy Terry", "Zach Hyman", "Josh Doan", "Connor Hellebuyck", "Topias Leinonen")}
    assert statuses == {"Troy Terry": "ltir", "Zach Hyman": "out", "Josh Doan": "day_to_day",
                        "Connor Hellebuyck": "suspended",   # listed as IR-NR with type "Suspension"
                        "Topias Leinonen": "ir"}
    assert by_name["Topias Leinonen"]["roster_status"] == "minors"
    assert {r["team"] for r in rows} == {"ANA", "BUF", "EDM", "FLA", "SJS", "WPG"}


def test_normalize_status_fallbacks():
    assert normalize_status({"status": "Out", "type": {"name": "INJURY_STATUS_OUT"}}) == "out"
    assert normalize_status({"status": "Day-To-Day"}) == "day_to_day"
    assert normalize_status({"status": "Injured Reserve", "details": {"fantasyStatus": {"abbreviation": "IR-LT"}}}) == "ltir"
    assert normalize_status({"status": "Suspension", "type": {"name": "INJURY_STATUS_SUSPENSION"}}) == "suspended"


def test_parse_handles_empty_and_odd_payloads():
    assert parse_injuries(None) == [] and parse_injuries({}) == []
    assert parse_injuries({"injuries": [{"injuries": [{"athlete": {"displayName": "No Id"}}]}]}) == []
    row = parse_injuries({"injuries": [{"injuries": [{"status": "Out", "athlete": {"uid": "s:70~l:90~a:123"}}]}]})[0]
    assert row["espn_athlete_id"] == 123 and row["team"] is None and row["report_date"] is None


# ---------- athlete matching ----------

def _index():
    players = [
        {"id": 1, "first_name": "Drew", "last_name": "Helleson", "position": "D", "current_team": "ANA"},
        {"id": 2, "first_name": "Samuel", "last_name": "Montembeault", "position": "G", "current_team": "MTL"},
        {"id": 3, "first_name": "Troy", "last_name": "Terry", "position": "R", "current_team": None},   # off the NHL roster on IR
        {"id": 4, "first_name": "Elias", "last_name": "Pettersson", "position": "C", "current_team": None},
        {"id": 5, "first_name": "Elias", "last_name": "Pettersson", "position": "D", "current_team": None},
        {"id": 6, "first_name": "Sam", "last_name": "Montembeault", "position": "C", "current_team": "MTL"},  # a skater namesake
    ]
    return build_player_index(players)


def test_match_injured_players():
    idx = _index()
    row = lambda name, team, pos, aid=99: {"espn_athlete_id": aid, "full_name": name, "first_name": name.split()[0],
                                           "last_name": name.split()[-1], "team": team, "position": pos}
    assert match_injured_player(idx, row("Drew Helleson", "ANA", "D")) == (1, "exact_team")
    # goalie flag keeps the skater namesake out; "Sam" / "Samuel" match loosely on the listed team
    assert match_injured_player(idx, row("Sam Montembeault", "MTL", "G")) == (2, "loose_team")
    assert match_injured_player(idx, row("Troy Terry", "ANA", "RW")) == (3, "exact_other_team")
    assert match_injured_player(idx, row("Elias Pettersson", "VAN", "C"))[0] is None   # namesakes, neither rostered
    assert match_injured_player(idx, row("Nobody Here", "VAN", "C")) == (None, "name_not_found")
    assert match_injured_player(idx, row("Nobody Here", "VAN", "C", aid=7), known={7: 42}) == (42, "known")


# ---------- which games a listing covers ----------

def _report_frame(**overrides):
    base = {"player_id": [10, 11, 12, 13, 14, None], "status": ["ir", "out", "day_to_day", "suspended", "ltir", "ir"],
            "report_date": [pd.Timestamp("2026-10-05 15:00", tz="UTC")] * 6,
            "return_date": [datetime.date(2026, 10, 12), None, None, datetime.date(2026, 10, 1),
                            datetime.date(2026, 12, 1), None]}
    base.update(overrides)
    return pd.DataFrame(base)


def test_listed_out_statuses_and_horizon():
    out = F.listed_out(_report_frame(), today=20261007)
    # day-to-day and unmatched rows stay in; IR through the day before the estimated return; no date = a week;
    # a past return date still covers tonight
    assert out.to_dict() == {10: 20261011, 11: 20261014, 13: 20261007, 14: 20261130}
    assert F.listed_out(None, today=20261007).empty


def test_listed_out_ignores_players_seen_playing_after_the_report():
    report = _report_frame(report_date=[pd.Timestamp("2026-10-07 02:30", tz="UTC")] * 6)   # night of Oct 6
    # 10 got hurt in the Oct 6 game (reported after it): still out. 11 played Oct 7: ESPN's entry is stale
    last_played = pd.Series({10: 20261006, 11: 20261007})
    assert set(F.listed_out(report, today=20261008, last_played=last_played).index) == {13, 14, 10}


# ---------- lineups ----------

def _lineups(game_ids=(100,), date="2026-10-08"):
    rows = [{"game_id": g, "team": "TOR", "date": pd.Timestamp(date), "player_id": p}
            for g in game_ids for p in (1, 2, 3, 4)]
    return pd.DataFrame(rows)


POSITIONS = pd.Series({1: "C", 2: "L", 3: "D", 4: "D", 5: "C", 6: "D", 7: "R", 8: "D", 9: "G"})
CANDIDATES = pd.DataFrame({"team": "TOR", "player_id": [5, 6, 7, 8, 9, 1],
                           "position": ["C", "D", "R", "D", "G", "C"], "exp_toi": [0.2, 0.3, 0.25, None, 0.5, 0.33]})


def test_drop_listed_out_replaces_within_position_group():
    out = pd.Series({1: 20261010, 3: 20261010, 7: 20261010})
    lu = F.drop_listed_out(_lineups(), out, POSITIONS, CANDIDATES)
    # forward 1 -> best healthy forward not in the lineup (7 is out too) = 5; defenceman 3 -> 6 (more ice time than 8)
    assert sorted(lu["player_id"]) == [2, 4, 5, 6]
    assert F.drop_listed_out(_lineups(), out, POSITIONS, None)["player_id"].tolist() == [2, 4]   # no pool: short


def test_drop_listed_out_only_inside_the_listing_and_given_games():
    out = pd.Series({1: 20261008})
    lu = pd.concat([_lineups((100,), "2026-10-08"), _lineups((101,), "2026-10-10")], ignore_index=True)
    after = F.drop_listed_out(lu, out, POSITIONS, CANDIDATES)
    assert 1 not in set(after.loc[after["game_id"] == 100, "player_id"])
    assert 1 in set(after.loc[after["game_id"] == 101, "player_id"])     # he's back by Oct 10
    same = F.drop_listed_out(lu, out, POSITIONS, CANDIDATES, game_ids={101})
    assert same.equals(lu)
    # backtests pass (game_id, player_id) pairs instead
    pairs = F.drop_listed_out(lu, pd.DataFrame({"game_id": [101], "player_id": [2]}), POSITIONS, CANDIDATES)
    assert sorted(pairs.loc[pairs["game_id"] == 101, "player_id"]) == [1, 3, 4, 7]   # 7 only out in the Series


def test_live_lineups_roster_rating_and_teammates_follow_the_report():
    # TOR played game 1 with skaters 1-4; game 2 is upcoming. Skater 1 (the best) is listed out.
    skaters = pd.DataFrame({"game_id": 1, "team": "TOR", "player_id": [1, 2, 3, 4],
                            "position": ["C", "L", "D", "D"], "game_date": 20261006})
    team_games = pd.DataFrame({"game_id": [1, 2], "team": "TOR", "season": 2026,
                               "date": pd.to_datetime(["2026-10-06", "2026-10-08"])})
    rosters = pd.DataFrame({"player_id": [1, 2, 3, 4, 5, 9], "team": "TOR", "position": ["C", "L", "D", "D", "C", "G"]})
    ratings = pd.DataFrame({"player_id": [1, 2, 3, 4, 5], "date": pd.Timestamp("2026-10-01"),
                            "exp_toi": [0.33, 0.3, 0.35, 0.3, 0.2], "exp_game_score": [1.0, 0.5, 0.4, 0.3, 0.1],
                            "exp_points": [0.9, 0.4, 0.3, 0.2, 0.1], "on_ice_xg_pct": 0.5})
    out = pd.Series({1: 20261010})
    base = P._live_lineups(team_games, skaters, rosters, ratings)
    live = P._live_lineups(team_games, skaters, rosters, ratings, out, upcoming={2})
    assert sorted(base.loc[base["game_id"] == 2, "player_id"]) == [1, 2, 3, 4]
    assert sorted(live.loc[live["game_id"] == 2, "player_id"]) == [2, 3, 4, 5]
    assert sorted(live.loc[live["game_id"] == 1, "player_id"]) == [1, 2, 3, 4]    # played games untouched
    before = F.roster_ratings(base, ratings).set_index("game_id")
    after = F.roster_ratings(live, ratings).set_index("game_id")
    assert after.loc[2, "roster_game_score"] == pytest.approx(before.loc[2, "roster_game_score"] - 1.0 + 0.1)
    # skater 2's teammates no longer include the injured 1
    players = pd.DataFrame({"game_id": [2], "team": "TOR", "player_id": [2]})
    mates = F.teammate_quality(players, F.rated_lineups(live, ratings))
    assert mates["teammates_game_score"].iloc[0] == pytest.approx(0.4 + 0.3 + 0.1)


def test_out_starter_replaced_unless_confirmed():
    team_games = pd.DataFrame({"game_id": [2, 3], "team": "WPG", "date": pd.to_datetime(["2026-10-08", "2026-10-08"])})
    picks = pd.DataFrame({"game_id": [2, 3], "team": "WPG", "player_id": [30, 30], "status": ["projected", "confirmed"]})
    goalies = pd.DataFrame({"game_id": [1, 1], "team": "WPG", "player_id": [30, 31], "toi": [3600, 0]})
    rosters = pd.DataFrame({"player_id": [30, 31, 32], "team": "WPG", "position": "G"})
    out = pd.Series({30: 20261016})
    new = F.replace_out_starters(picks, out, team_games, goalies, rosters, game_ids={2, 3})
    assert new.loc[0, "player_id"] in (31, 32) and new.loc[0, "status"] == "projected"
    assert new.loc[1, "player_id"] == 30 and new.loc[1, "status"] == "confirmed"


# ---------- storage and fallbacks ----------

def run(coro_fn):
    async def go():
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return await coro_fn(db)
    return asyncio.run(go())


def test_snapshots_append_and_latest_recent_one_is_used():
    t0 = datetime.datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
    rows = [{**r, "player_id": i} for i, r in enumerate(_report())]

    async def go(db):
        await insert_injury_snapshot(db, rows, t0)
        await insert_injury_snapshot(db, rows[:5] + rows[:2], t0 + datetime.timedelta(hours=6))   # duplicates dropped
        latest = await load_injury_report(db, as_of=t0 + datetime.timedelta(hours=7))
        earlier = await load_injury_report(db, as_of=t0 + datetime.timedelta(hours=1))
        stale = await load_injury_report(db, as_of=t0 + datetime.timedelta(days=3))
        return latest, earlier, stale
    latest, earlier, stale = run(go)
    assert len(latest) == 5 and len(earlier) == 31
    assert stale is None                    # ESPN down for days: no report, lineups fall back to the previous game's


def test_context_without_a_report_matches_previous_behaviour():
    skaters = pd.DataFrame({"game_id": 1, "team": "TOR", "player_id": [1, 2], "position": "C", "game_date": 20261006})
    team_games = pd.DataFrame({"game_id": [1, 2], "team": "TOR", "season": 2026,
                               "date": pd.to_datetime(["2026-10-06", "2026-10-08"])})
    rosters = pd.DataFrame({"player_id": [1, 2], "team": "TOR", "position": "C"})
    ratings = pd.DataFrame({"player_id": [1, 2], "exp_toi": [0.3, 0.3]})
    goalies = pd.DataFrame(columns=["player_id", "game_date"])
    assert P._injured_out(None, skaters, goalies).empty
    assert P._live_lineups(team_games, skaters, rosters, ratings, P._injured_out(None, skaters, goalies), {2}).equals(
        P._live_lineups(team_games, skaters, rosters, ratings))


def test_prediction_log_skips_listed_out_skaters(monkeypatch):
    from types import SimpleNamespace
    from predictions import prediction_log as PL
    ctx = {"lineups": pd.DataFrame({"game_id": [7, 7], "player_id": [2, 3]}),
           "injured_out": pd.Series({1: 20261010, 5: 20261001})}

    async def fake_context(db):
        return ctx
    monkeypatch.setattr(P, "_team_context", fake_context)
    dressing, out = asyncio.run(PL._expected_skaters(None, SimpleNamespace(id=7, date=20261008)))
    assert dressing == {2, 3} and out == {1}     # 5's listing ended before this game
