"""Lineups, scratches and projected lines: NHL shift chart / play-by-play / right-rail / HTML TOI report parsing
(saved fixtures from TOR @ VGK, 2026020065, no network), the 5-on-5 / power-play / penalty-kill deployment rebuilt
from shifts, the line projection, and the stored tables behind GET /teams/{tri}/lineup."""
import asyncio
import datetime
import itertools
import json
import os
import random
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import deployment as D
from app import line_projection as L
from app.crud import lineups as CL
from app.models import Base, Games, GameStarter, Player, PlayerInjury, Team
from external.nhl import lineups as N

FIX = Path(__file__).parent / "fixtures" / "nhl"
GAME = 2026020065
TANEV, MCCABE, MATTHEWS, BLUEGER, DUHAIME = 8475690, 8476931, 8479318, 8476927, 8479520
BOBROVSKY, STOLARZ = 8475683, 8476932
MACEWEN, BLANKENBURG = 8479772, 8483565
NOW = datetime.datetime(2026, 10, 10, 12, 0, tzinfo=datetime.timezone.utc)


def _load(name):
    return json.loads((FIX / name).read_text())


def _game_data():
    pbp = _load("pbp_2026020065_lineups.json")
    return N.GameLineupData(game_id=GAME, home="VGK", away="TOR", roster_spots=N.parse_roster_spots(pbp),
                            scratches=N.parse_scratches(_load("rightrail_2026020065.json"), "VGK", "TOR"),
                            shifts=N.parse_shifts(_load("shiftcharts_2026020065.json")), faceoffs=N.parse_faceoffs(pbp),
                            last_period=N.parse_last_period(pbp))


def _deployments(data=None):
    data = data or _game_data()
    positions = {s.player_id: s.position for s in data.roster_spots}
    return D.game_deployment(data.shifts, positions, ("VGK", "TOR"))


# ---------- NHL parsing ----------

def test_shift_chart_keeps_shifts_only():
    payload = {"data": [
        {"typeCode": 517, "playerId": 1, "teamAbbrev": "TOR", "period": 1, "startTime": "00:00", "endTime": "00:40"},
        {"typeCode": 505, "playerId": 1, "teamAbbrev": "TOR", "period": 1, "startTime": "05:00", "endTime": "05:00"},
        {"typeCode": 517, "playerId": 2, "teamAbbrev": "TOR", "period": 1, "startTime": "01:00", "endTime": None},
        {"typeCode": 517, "playerId": 3, "teamAbbrev": "TOR", "period": 2, "startTime": "03:00", "endTime": "02:00"},
    ]}
    assert N.parse_shifts(payload) == [N.Shift(player_id=1, team="TOR", period=1, start=0, end=40)]
    assert N.parse_shifts(None) == [] and N.parse_shifts({"data": [], "total": 0}) == []


def test_roster_spots_scratches_and_faceoffs():
    data = _game_data()
    assert len(data.roster_spots) == 40
    tor = [s for s in data.roster_spots if s.team == "TOR"]
    assert sum(s.position == "G" for s in tor) == 2 and sum(s.position == "D" for s in tor) == 6
    assert {(s.team, s.player_id, s.last_name) for s in data.scratches} == {
        ("TOR", MACEWEN, "MacEwen"), ("TOR", BLANKENBURG, "Blankenburg"),
        ("VGK", 8478109, "Olofsson"), ("VGK", 8479639, "Coghlan")}
    assert data.faceoffs[MATTHEWS] == 21
    assert N.parse_scratches({"gameInfo": {"homeTeam": {"scratches": []}}}, "VGK", "TOR") == []


def test_html_toi_report_matches_the_shift_chart():
    data = _game_data()
    numbers = {s.sweater_number: s.player_id for s in data.roster_spots if s.team == "TOR"}
    from_report = N.parse_toi_report((FIX / "toi_TV020065.htm").read_text(), "TOR", numbers)
    players = {s.player_id for s in from_report}
    assert len(players) == 3 and TANEV in players
    assert set(from_report) == {s for s in data.shifts if s.player_id in players}
    assert N.parse_toi_report(None, "TOR", numbers) == []
    assert N.toi_report_url(2026020008, "H") == "https://www.nhl.com/scores/htmlreports/20262027/TH020008.HTM"


# ---------- deployment ----------

def _shift(player, team, start, end, period=1):
    return N.Shift(player_id=player, team=team, period=period, start=start, end=end)


def test_strength_states_and_units():
    # home: forwards 1-3, D 4-5, goalie 9; away: forwards 11-13, D 14-15, goalie 19
    positions = {1: "C", 2: "L", 3: "R", 4: "D", 5: "D", 9: "G", 11: "C", 12: "L", 13: "R", 14: "D", 15: "D", 19: "G"}
    shifts = [_shift(p, "HOM", 0, 100) for p in (1, 2, 3, 4, 5, 9)] + [_shift(p, "AWY", 0, 100) for p in (11, 12, 13, 14, 15, 19)]
    shifts[1] = _shift(2, "HOM", 0, 60)                  # home LW off at 60: home short-handed for 40 seconds
    shifts += [_shift(15, "AWY", 100, 120)]              # after 100 only one skater: no strength counted
    dep = D.game_deployment(shifts, positions, ("HOM", "AWY"))
    home, away = dep["HOM"], dep["AWY"]
    assert home.units[D.EV_FORWARDS] == {"1-2-3": 60} and home.units[D.EV_DEFENSE] == {"4-5": 60}
    assert home.units[D.PK] == {"1-3-4-5": 40} and away.units[D.PP] == {"11-12-13-14-15": 40}
    assert home.toi_ev[1] == 60 and home.toi_pk[1] == 40 and home.toi[1] == 100 and home.toi[9] == 100
    assert away.toi_pp[11] == 40 and away.toi[15] == 120 and away.toi_ev[15] == 60


def test_pulled_goalie_is_not_a_power_play():
    positions = {1: "C", 2: "L", 3: "R", 4: "D", 5: "D", 6: "C", 9: "G", 11: "C", 12: "L", 13: "R", 14: "D", 15: "D", 19: "G"}
    shifts = [_shift(p, "HOM", 0, 60) for p in (1, 2, 3, 4, 5, 6)] + [_shift(p, "AWY", 0, 60) for p in (11, 12, 13, 14, 15, 19)]
    dep = D.game_deployment(shifts, positions, ("HOM", "AWY"))     # 6 on 5 with the home net empty
    assert not dep["HOM"].units[D.PP] and not dep["AWY"].units[D.PK] and not dep["HOM"].toi_ev


def test_real_game_deployment():
    dep = _deployments()
    tor = dep["TOR"]
    assert tor.units[D.EV_DEFENSE].most_common(1) == [(D.unit_key((TANEV, MCCABE)), 945)]
    assert tor.units[D.PK].most_common(1)[0] == (D.unit_key((TANEV, MCCABE, BLUEGER, DUHAIME)), 246)
    # Toronto killed four minors (480 s) and had one power play plus a few seconds of a 4-on-3 (120 s)
    assert sum(tor.units[D.PK].values()) == 480 and sum(tor.units[D.PP].values()) == 120
    assert sum(tor.toi_ev.values()) == 5 * 2980
    shifts, teams = _game_data().shifts, ("VGK", "TOR")
    assert _game_data().last_period == (5, "SO")
    assert D.shifts_cover_game(shifts, teams, (5, "SO"))                   # overtime played, shootout has no shifts
    assert not D.shifts_cover_game([s for s in shifts if s.period < 4], teams, (5, "SO"))   # overtime missing
    assert not D.shifts_cover_game([s for s in shifts if s.period < 3], teams)
    # the last shifts of the third not in yet (a chart still filling in after the horn)
    assert not D.shifts_cover_game([s for s in shifts if not (s.period == 3 and s.end > 1150)], teams, (5, "SO"))
    rows = D.unit_rows(GAME, dep)
    assert {r["situation"] for r in rows} == set(D.SITUATIONS) and all(r["seconds"] >= 1 for r in rows)


# ---------- projection ----------

def test_best_partition_is_exact():
    rng = random.Random(7)
    players = list(range(1, 8))
    scores = {g: rng.random() for g in itertools.combinations(players, 3)}
    score = lambda g: scores[tuple(sorted(g))]
    got = L.best_partition(players, 3, 2, score)            # 7 players, 2 trios: one sits out
    best = max(((a, b) for a in scores for b in scores if not set(a) & set(b)), key=lambda ab: score(ab[0]) + score(ab[1]))
    assert len(got) == 2 and sum(map(score, got)) == sum(map(score, best))
    assert L.best_partition([1, 2], 3, 4, score) == []


def test_slots():
    positions = {1: "C", 2: "C", 3: "R"}
    assert L.forward_slots((1, 2, 3), positions, {1: "L", 2: "R"}, {1: 2.0, 2: 15.0}) == [("LW", 1), ("C", 2), ("RW", 3)]
    assert L.defense_slots((4, 5), {4: "R", 5: "L"}, {4: 1000, 5: 900}) == [("LD", 5), ("RD", 4)]
    assert L.defense_slots((4, 5), {4: "L", 5: "L"}, {4: 900, 5: 1000}) == [("LD", 5), ("RD", 4)]


def _lineup(game_id, forwards, defense, goalies=(90, 91), scratched=(), toi=900):
    rows = [{"game_id": game_id, "player_id": p, "status": "dressed", "position": pos, "toi": toi, "toi_ev": toi - i,
             "faceoffs": 10 if pos == "C" else 0}
            for i, (p, pos) in enumerate(list(forwards.items()) + [(d, "D") for d in defense] + [(g, "G") for g in goalies])]
    return rows + [{"game_id": game_id, "player_id": p, "status": "scratched", "position": None, "toi": None}
                   for p in scratched]


FWD = {1: "C", 2: "L", 3: "R", 4: "C", 5: "L", 6: "R", 7: "C", 8: "L", 9: "R", 10: "C", 11: "L", 12: "R"}
DEF = (21, 22, 23, 24, 25, 26)


def _units(game_id, trios, pairs, pp=(), pk=()):
    rows = [{"game_id": game_id, "situation": D.EV_FORWARDS, "unit": D.unit_key(t), "seconds": 600 - 100 * i}
            for i, t in enumerate(trios)]
    rows += [{"game_id": game_id, "situation": D.EV_DEFENSE, "unit": D.unit_key(p), "seconds": 700 - 100 * i}
             for i, p in enumerate(pairs)]
    rows += [{"game_id": game_id, "situation": D.PP, "unit": D.unit_key(u), "seconds": 120 - 30 * i} for i, u in enumerate(pp)]
    rows += [{"game_id": game_id, "situation": D.PK, "unit": D.unit_key(u), "seconds": 100 - 30 * i} for i, u in enumerate(pk)]
    return rows


TRIOS = [(1, 2, 3), (4, 5, 6), (7, 8, 9), (10, 11, 12)]
PAIRS = [(21, 22), (23, 24), (25, 26)]


def _history():
    old = L.PastGame(1, _lineup(1, FWD, DEF), _units(1, [(1, 5, 9), (4, 2, 6), (7, 8, 3), (10, 11, 12)], PAIRS))
    new = L.PastGame(2, _lineup(2, FWD, DEF, scratched=(13,)),
                     _units(2, TRIOS, PAIRS, pp=[(1, 2, 3, 4, 21), (5, 6, 7, 8, 22)], pk=[(10, 11, 23, 24)]))
    return [new, old]


def test_lines_follow_the_newest_game():
    proj = L.project_lineup(_history(), [], {})
    assert proj.lineup_status == "projected" and proj.based_on == [2, 1]
    assert [tuple(sorted(u.players)) for u in proj.forwards] == TRIOS
    assert [u.slots for u in proj.forwards][0] == [("LW", 2), ("C", 1), ("RW", 3)]
    assert [tuple(sorted(u.players)) for u in proj.defense] == PAIRS
    assert proj.forwards[0].seconds_last_game == 600 and proj.forwards[0].games_together == 1
    assert sorted(proj.power_play[0].players) == [1, 2, 3, 4, 21] and proj.power_play[0].slots[-1] == ("D", 21)
    assert sorted(proj.penalty_kill[0].players) == [10, 11, 23, 24]
    assert not proj.extras and proj.changes == {"in": [], "out": []}


def test_injured_player_is_replaced_by_the_scratch_and_keeps_his_linemates_together():
    roster = [L.RosterPlayer(p, pos) for p, pos in FWD.items()] + [L.RosterPlayer(13, "C")] + \
             [L.RosterPlayer(d, "D") for d in DEF] + [L.RosterPlayer(90, "G"), L.RosterPlayer(91, "G")]
    proj = L.project_lineup(_history(), roster, {2: "ir", 5: "day_to_day"})
    assert 2 not in proj.dressed and 13 in proj.dressed and 5 in proj.dressed
    assert proj.changes == {"in": [13], "out": [2]}
    line = next(u for u in proj.forwards if 1 in u.players)
    assert {1, 3} <= set(line.players)                        # the pair left behind stays together
    assert 2 not in proj.power_play[0].players


def test_traded_player_leaves_and_posted_lineup_is_confirmed():
    roster = [L.RosterPlayer(p, pos) for p, pos in FWD.items() if p != 12] + [L.RosterPlayer(13, "R")] + \
             [L.RosterPlayer(d, "D") for d in DEF] + [L.RosterPlayer(90, "G"), L.RosterPlayer(91, "G")]
    proj = L.project_lineup(_history(), roster, {})
    assert 12 not in proj.dressed and 13 in proj.dressed
    posted = [r for r in _lineup(3, {**FWD, 14: "C"}, DEF) if r["player_id"] != 12]
    confirmed = L.project_lineup(_history(), [], {}, posted=posted)
    assert confirmed.lineup_status == "confirmed" and 14 in confirmed.dressed and 12 not in confirmed.dressed


def test_regular_back_from_injury_replaces_the_least_used_forward_but_a_healthy_scratch_stays_out():
    # player 30 averaged the most ice time over three games, then missed the last one (13 dressed in his place)
    star = {1: "C", 2: "L", 3: "R", 4: "C", 5: "L", 6: "R", 7: "C", 8: "L", 9: "R", 10: "C", 11: "L", 30: "R"}
    games = [L.PastGame(g, [{**r, "toi_ev": 1500} if r["player_id"] == 30 else r for r in _lineup(g, star, DEF)],
                        _units(g, [(1, 2, 30), (4, 5, 6), (7, 8, 9), (10, 11, 3)], PAIRS)) for g in (1, 2, 3)]
    last_lineup = {**{p: pos for p, pos in star.items() if p != 30}, 13: "R"}
    last = L.PastGame(4, [{**r, "toi_ev": 100} if r["player_id"] == 13 else r for r in _lineup(4, last_lineup, DEF)],
                      _units(4, [(1, 2, 3), (4, 5, 6), (7, 8, 9), (10, 11, 13)], PAIRS))
    history = [last] + games[::-1]
    assert 30 not in L.project_lineup(history, [], {30: "out"}, returning={30}).dressed      # still listed
    assert 30 not in L.project_lineup(history, [], {}).dressed                              # coach's call
    proj = L.project_lineup(history, [], {}, returning={30})                               # off the report
    assert 30 in proj.dressed and 13 not in proj.dressed and proj.changes == {"in": [30], "out": [13]}


def test_no_history_means_no_projection():
    assert L.project_lineup([], [], {}) is None


# ---------- stored tables and the endpoint ----------

def _run(coro_fn):
    async def go():
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return await coro_fn(db)
    return asyncio.run(go())


def _game(gid, start, state="OFF", home="VGK", away="TOR"):
    return Games(id=gid, home_team_tri_code=home, away_team_tri_code=away, season=20262027, date=20261008, venue="v",
                 start_time=start, game_state=state, last_updated=start)


def test_store_and_query_lineups():
    async def go(db):
        db.add_all([_game(GAME, NOW - datetime.timedelta(days=2)), _game(2026020080, NOW + datetime.timedelta(hours=1), "FUT", "COL", "TOR"),
                    _game(2026020070, NOW - datetime.timedelta(days=1))])
        await db.commit()
        data = _game_data()
        assert {g.id for g in await CL.get_games_missing_deployment(db, 2026, now=NOW)} == {GAME, 2026020070}
        # posted before puck drop: dressed and scratched, no ice time yet
        assert await CL.store_game_lineup(db, data) == 44
        missing = await CL.get_games_missing_deployment(db, 2026, now=NOW)
        assert GAME in {g.id for g in missing}
        assert GAME not in {g.id for g in await CL.get_games_missing_deployment(db, 2026, recheck_days=1, now=NOW)}
        # after the game, with the shift chart: replaces the rows, adds units
        await CL.store_game_lineup(db, data, _deployments(data))
        assert GAME not in {g.id for g in await CL.get_games_missing_deployment(db, 2026, now=NOW)}
        rows = await CL.load_lineups(db, "TOR", [GAME])
        assert len(rows) == 22 and sum(r["status"] == "scratched" for r in rows) == 2
        assert next(r for r in rows if r["player_id"] == TANEV)["toi_ev"] > 0
        units = await CL.load_units(db, "TOR", [GAME])
        assert {"situation": "ev_d", "unit": D.unit_key((TANEV, MCCABE)), "seconds": 945, "game_id": GAME} in units
        # nothing posted for the next game: it awaits its lineups once within the lead time
        assert [g.id for g in await CL.get_games_awaiting_lineups(db, now=NOW)] == [2026020080]
        empty = N.GameLineupData(2026020080, "COL", "TOR", [], [], None, {})
        assert await CL.store_game_lineup(db, empty) == 0
        recent = await CL.get_recent_lineup_games(db, "TOR")
        assert [g.game_id for g in recent] == [GAME] and recent[0].opponent == "VGK" and not recent[0].home
        nxt = await CL.get_next_team_game(db, "TOR", now=NOW)
        assert nxt.game_id == 2026020080 and nxt.opponent == "COL"
    _run(go)


def test_lineup_polling_windows_and_game_types():
    async def go(db):
        db.add_all([_game(2026020080, NOW + datetime.timedelta(minutes=30), "FUT", "COL", "TOR"),
                    _game(2026010080, NOW + datetime.timedelta(minutes=30), "FUT", "BOS", "MTL"),     # preseason
                    _game(2026020090, NOW - datetime.timedelta(days=20), "FUT", "TOR", "OTT"),        # postponed
                    _game(2026020091, NOW - datetime.timedelta(hours=3), "LIVE", "EDM", "CGY")])      # never posted
        await db.commit()
        assert [g.id for g in await CL.get_games_awaiting_lineups(db, now=NOW)] == [2026020080]
        # once posted it is fetched again until 15 minutes after puck drop (a late change), then left alone
        data = _game_data()
        for spot in data.roster_spots:
            object.__setattr__(spot, "team", "TOR" if spot.team == "TOR" else "COL")
        await CL.store_game_lineup(db, N.GameLineupData(2026020080, "COL", "TOR", data.roster_spots, [], None, {}))
        assert [g.id for g in await CL.get_games_awaiting_lineups(db, now=NOW)] == [2026020080]
        assert await CL.get_games_awaiting_lineups(db, now=NOW + datetime.timedelta(minutes=50)) == []
        # a game stuck before its final score weeks ago is not the next game
        assert (await CL.get_next_team_game(db, "TOR", now=NOW)).game_id == 2026020080
    _run(go)


def test_failed_scratch_fetch_keeps_stored_scratches_and_back_off():
    async def go(db):
        db.add(_game(GAME, NOW - datetime.timedelta(hours=5)))
        await db.commit()
        data = _game_data()
        await CL.store_game_lineup(db, data, fetched_at=NOW - datetime.timedelta(hours=4))
        assert [g.id for g in await CL.get_games_missing_deployment(db, 2026, now=NOW, fetched_before=NOW - datetime.timedelta(minutes=30))] == [GAME]
        no_rail = N.GameLineupData(GAME, "VGK", "TOR", data.roster_spots, None, data.shifts, data.faceoffs)
        await CL.store_game_lineup(db, no_rail, _deployments(data), fetched_at=NOW)
        rows = await CL.load_lineups(db, "TOR", [GAME])
        assert {r["player_id"] for r in rows if r["status"] == "scratched"} == {MACEWEN, BLANKENBURG}
        assert all(r["toi"] is not None for r in rows if r["status"] == "dressed")
    _run(go)


def test_team_lineup_endpoint_data():
    from app.team_lineup import build_team_lineup

    async def go(db):
        db.add_all([Team(tri_code=t, current_name=t, franchise_id=1) for t in ("TOR", "VGK", "COL")])
        db.add_all([_game(GAME, NOW - datetime.timedelta(days=2)), _game(2026020080, NOW + datetime.timedelta(hours=8), "FUT", "COL", "TOR")])
        data = _game_data()
        for s in data.roster_spots + [N.RosterSpot(MACEWEN, "TOR", "R", 19, "Zack", "MacEwen"),
                                      N.RosterSpot(BLANKENBURG, "TOR", "D", 3, "Nick", "Blankenburg")]:
            if s.team == "TOR":
                db.add(Player(id=s.player_id, first_name=s.first_name, last_name=s.last_name, number=s.sweater_number,
                              position=s.position, current_team_tri_code="TOR", shoots_catches="L"))
        # Tanev listed out, Blankenburg day-to-day: Tanev leaves the lineup and Blankenburg's scratch isn't healthy
        # one snapshot, read as of now, so stored as fetched an hour ago
        fetched = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        for i, (pid, status) in enumerate(((TANEV, "ir"), (BLANKENBURG, "day_to_day"))):
            db.add(PlayerInjury(fetched_at=fetched, espn_athlete_id=i + 1, player_id=pid,
                                team="TOR", full_name=str(pid), status=status, injury_type="Lower Body"))
        db.add(GameStarter(game_id=2026020080, team="TOR", source="espn", player_id=STOLARZ, status="probable",
                           fetched_at=NOW))
        # a listing with no report date (NaT once in a DataFrame) must still serialize
        db.add(PlayerInjury(fetched_at=fetched, espn_athlete_id=9, player_id=None, team="TOR", full_name="Minor Leaguer",
                            status="out", report_date=None))
        await db.commit()
        await CL.store_game_lineup(db, data, _deployments(data))
        out = await build_team_lineup(db, "tor")
        assert out.team == "TOR" and out.status == "projected" and out.game.opponent == "COL" and out.basedOn == [GAME]
        assert len(out.forwards) == 4 and len(out.defense) == 3
        dressed = {p.id for u in out.forwards + out.defense for p in u.players}
        assert TANEV not in dressed and BLANKENBURG in dressed       # the only healthy D: he draws in
        assert [p.id for p in out.changes.playersOut] == [TANEV] and [p.id for p in out.changes.playersIn] == [BLANKENBURG]
        assert {(s.player.id, s.healthy, s.gamesScratched) for s in out.scratches} == {(MACEWEN, True, 1)}
        assert {i.playerId: i.status for i in out.injuries} == {TANEV: "ir", BLANKENBURG: "day_to_day", None: "out"}
        out.model_dump_json()
        assert out.injuries[0].playerId == TANEV                     # out before day-to-day
        # ESPN's probable starter tonight; last game's starter (Bobrovsky) is the backup
        assert [(g.role, g.player.id, g.status) for g in out.goalies] == [
            ("starter", STOLARZ, "probable"), ("backup", BOBROVSKY, "projected")]
        assert len(out.powerPlay) == 2 and len(out.penaltyKill) == 2
        assert out.injuryReportAsOf is not None and out.lineupsUpdatedAt is not None
    _run(go)
