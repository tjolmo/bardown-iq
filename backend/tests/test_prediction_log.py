import asyncio
import datetime
import math
import os
import sys

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.crud import odds_snapshots as S
from app.models import (Base, GameOddsSnapshot, Games, GoalieGameLog, PropQuote, Player, PlayerPredictionLog,
                        PlayerPropSnapshot, PredictionLog, PredictionScore, SkaterGameLog, Team)
from predictions import prediction_log as PL

NOW = datetime.datetime(2026, 10, 8, 21, 0, tzinfo=datetime.timezone.utc)
H = datetime.timedelta(hours=1)


def run(coro_fn):
    async def go():
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return await coro_fn(db)
    return asyncio.run(go())


def game(gid, start, state, home="TOR", away="MTL", date=20261008, hs=None, as_=None):
    return Games(id=gid, home_team_tri_code=home, away_team_tri_code=away, season=20262027, date=date, venue="v",
                 start_time=start, game_state=state, home_score=hs, away_score=as_, last_updated=NOW)


def odds_row(gid, home_ml=-150, away_ml=130, p=0.58):
    return {"game_id": gid, "home_moneyline": home_ml, "away_moneyline": away_ml, "home_prob_novig": p,
            "total_line": 6.5, "total_over_price": -110, "total_under_price": -110, "n_books": 1, "books": "DK"}


def prop_row(gid, pid=1, prop="shots_on_goal", line=2.5, over=-120, under=100, book="DK"):
    return {"game_id": gid, "player_id": pid, "prop_type": prop, "line": line, "book": book,
            "over_price": over, "under_price": under, "sides_inferred": True, "espn_last_updated": None}


def quote(gid, pid=1, key="player_goals", side="Over", line=0.5, odds=150, book="draftkings", first=None, last=None,
          first_odds=None, provider="propline"):
    first = first or NOW - 3 * H
    return {"game_id": gid, "player_id": pid, "prop_type": key, "over_under": side, "line": line, "bookmaker": book,
            "odds": odds, "first_odds": odds if first_odds is None else first_odds, "first_seen": first,
            "last_seen": last or first, "book_last_update": None, "event_id": "e", "provider": provider}


# ---------- snapshots ----------

def test_snapshot_phase():
    assert S.snapshot_phase(NOW + H, "FUT", NOW) == "pregame"
    assert S.snapshot_phase(NOW - H, "LIVE", NOW) is None          # in progress: never record in-game prices
    assert S.snapshot_phase(NOW - H, "FUT", NOW) is None           # stale / postponed
    assert S.snapshot_phase(NOW - 5 * H, "OFF", NOW) == "closing"
    assert S.snapshot_phase(None, "FUT", NOW) is None


def test_game_snapshots_skip_started_games_and_close_once():
    async def go(db):
        db.add_all([game(1, NOW + H, "FUT"), game(2, NOW - H, "LIVE"), game(3, NOW - 5 * H, "OFF")])
        await db.commit()
        rows = [odds_row(1), odds_row(2), odds_row(3), odds_row(99)]   # 99: unknown game
        first = await S.insert_game_odds_snapshots(db, rows, NOW)
        second = await S.insert_game_odds_snapshots(db, rows, NOW + datetime.timedelta(minutes=5))
        snaps = (await db.execute(select(GameOddsSnapshot).order_by(GameOddsSnapshot.id))).scalars().all()
        return first, second, [(s.game_id, s.is_closing) for s in snaps], snaps[0]
    first, second, snaps, snap = run(go)
    assert first == 2 and second == 1                  # game 3's close is written once, game 2 (live) never
    assert snaps == [(1, False), (3, True), (1, False)]
    assert snap.over_price == -110 and snap.home_prob_novig == 0.58


def test_prop_snapshots_skip_live_games_and_read_back():
    async def go(db):
        db.add_all([game(1, NOW + H, "FUT"), game(2, NOW - H, "LIVE")])
        await db.commit()
        n = await S.insert_player_prop_snapshots(db, [prop_row(1), prop_row(1), prop_row(1, line=3.5), prop_row(2)], NOW)
        await S.insert_player_prop_snapshots(db, [prop_row(1, over=-140, under=115)], NOW + H / 2)
        latest = await S.latest_prop_snapshots(db, [1], NOW + H / 4)
        newest = await S.latest_prop_snapshots(db, [1], NOW + H)
        close = await S.closing_prop_snapshots(db, [1])
        return n, latest, newest, close
    n, latest, newest, close = run(go)
    assert n == 2                                       # duplicate collapsed, live game skipped
    assert len(latest[1]) == 2 and len(newest[1]) == 1 and newest[1][0].over_price == -140
    assert close[1][0].over_price == -140               # last pre-game capture before the start


# ---------- scoring math ----------

def test_log_loss_and_deviance():
    assert PL.log_loss(0.6, 1) == pytest.approx(-math.log(0.6))
    assert PL.log_loss(0.6, 0) == pytest.approx(-math.log(0.4))
    assert PL.log_loss(0.6, None) is None
    assert PL.poisson_deviance(0, 0.5) == pytest.approx(1.0)
    assert PL.poisson_deviance(2, 2) == pytest.approx(0.0)
    assert PL.poisson_deviance(3, 1.5) == pytest.approx(2 * (3 * math.log(2) - 1.5))


def test_clv_sign():
    # model likes home more than the market; market moves toward home -> positive CLV
    assert PL.clv_prob(0.60, 0.55, 0.57) == pytest.approx(0.02)
    assert PL.clv_prob(0.60, 0.55, 0.53) == pytest.approx(-0.02)
    # model likes away (home prob below market); market moving away from home is positive
    assert PL.clv_prob(0.45, 0.55, 0.52) == pytest.approx(0.03)
    # got +120, closed +100: beat the close
    assert PL.price_clv(120, 100) == pytest.approx(2.2 / 2.0 - 1)
    assert PL.price_clv(-150, -130) < 0


def test_pick_side_threshold():
    assert PL.pick_side(0.60, 0.55, ("home", "away")) == ("home", pytest.approx(0.05))
    assert PL.pick_side(0.40, 0.45, ("home", "away")) == ("away", pytest.approx(0.05))
    assert PL.pick_side(0.56, 0.55, ("home", "away")) == (None, None)


def test_score_team():
    log = {"home_win_prob": 0.60, "market_home_prob_novig": 0.55, "market_home_moneyline": -110, "market_away_moneyline": -110}
    close = {"home_prob_novig": 0.58, "home_moneyline": -140, "away_moneyline": 120}
    s = PL.score_team(log, 4, 2, close)
    assert s["outcome"] == 1 and s["bet_side"] == "home"
    assert s["log_loss"] == pytest.approx(-math.log(0.6))
    assert s["clv_prob"] == pytest.approx(0.03) and s["clv_price"] > 0
    assert s["bet_profit"] == pytest.approx(100 / 110)
    lost = PL.score_team(log, 1, 2, None)              # no close: no CLV, still scored
    assert lost["bet_profit"] == -1.0 and lost["clv_prob"] is None and lost["market_log_loss_close"] is None


def test_score_player_over_under_push():
    log = {"stat": "shots_on_goal", "expected": 3.4, "market_line": 2.5, "market_over_price": -110,
           "market_under_price": -110, "market_over_prob_novig": 0.5}
    close_rows = [prop_row(1, line=2.5, over=-140, under=115)]
    s = PL.score_player(log, 4.0, close_rows)
    assert s["status"] == "scored" and s["outcome"] == 1 and s["bet_side"] == "over"
    assert s["model_prob"] > 0.6 and s["clv_prob"] > 0 and s["clv_price"] > 0 and s["bet_profit"] > 0
    push = PL.score_player({**log, "market_line": 3.0}, 3.0, None)
    assert push["status"] == "push" and push["outcome"] is None and push["log_loss"] is None
    assert PL.score_player({**log, "stat": "pp_points"}, 1.0, None)["status"] == "no_line"   # unpriced stat


def test_main_prop_market_prefers_most_books():
    rows = [prop_row(1, line=2.5, book="A"), prop_row(1, line=2.5, book="B", over=-115, under=-105),
            prop_row(1, line=3.5, over=150, under=-180, book="A"),
            prop_row(1, line=1.5, over=-300, under=None, book="C")]
    m = PL.main_prop_market(rows)
    assert m["line"] == 2.5 and m["n_books"] == 2 and 0.5 < m["p_over"] < 0.56


def test_quote_book_rows_pairs_sides_as_of():
    t1, t2 = NOW - 5 * H, NOW - 2 * H
    quotes = [
        # draftkings seen at both fetches, price moved from +150 to +140
        quote(1, side="Over", odds=140, first_odds=150, first=t1, last=t2),
        quote(1, side="Under", odds=-170, first_odds=-180, first=t1, last=t2),
        # fanduel pulled its market after the first fetch: gone at the later fetch
        quote(1, side="Over", odds=160, book="fanduel", first=t1, last=t1),
        quote(1, side="Under", odds=-200, book="fanduel", first=t1, last=t1),
        quote(1, side="Yes", key="player_goal_scorer_anytime", odds=150, first=t2),   # not a priced market key
        quote(1, side="Over", key="player_shots_on_goal", line=2.5, odds=-110, first=t2),   # one side only
        # PropLine books outside the consensus are stored but not counted
        quote(1, side="Over", odds=180, book="bovada", first=t2),
        quote(1, side="Under", odds=-220, book="bovada", first=t2),
    ]
    now = PL.quote_book_rows(quotes, NOW)
    goals = now[(1, 1, "goals")]
    assert [(r["book"], r["over_price"], r["under_price"]) for r in goals] == [("draftkings", 140, -170)]
    assert goals[0]["captured_at"] == t2 and goals[0]["provider"] == "propline"
    assert now[(1, 1, "shots_on_goal")][0]["under_price"] is None
    # between the fetches: both books, at their first-fetch prices
    early = PL.quote_book_rows(quotes, t1 + H)
    assert sorted((r["book"], r["over_price"]) for r in early[(1, 1, "goals")]) == [("draftkings", 150), ("fanduel", 160)]
    assert PL.quote_book_rows(quotes, t1 - H) == {}


def test_quote_book_rows_keeps_every_odds_api_book():
    # rows from before PropLine have no consensus filter (and no provider column value: the Odds API)
    quotes = [quote(1, side=side, odds=odds, book="bovada", provider=None) for side, odds in (("Over", 150), ("Under", -180))]
    rows = PL.quote_book_rows(quotes, NOW)[(1, 1, "goals")]
    assert [(r["book"], r["provider"]) for r in rows] == [("bovada", "odds_api")]


def test_pick_market_prefers_espn_then_quotes():
    espn = [S_row(prop_row(1, line=2.5))]
    api = [{"line": 3.5, "over_price": 110, "under_price": -130, "book": b, "captured_at": NOW - H,
            "provider": "propline"} for b in ("draftkings", "fanduel")]
    m, source, at = PL.pick_market(espn, api)
    assert source == "espn" and m["line"] == 2.5 and at == NOW - 2 * H
    m, source, at = PL.pick_market([], api)
    assert source == "propline" and m["line"] == 3.5 and m["n_books"] == 2 and at == NOW - H
    # an ESPN one-sided price (no under) is no line: fall back
    assert PL.pick_market([S_row(prop_row(1, under=None))], api)[1] == "propline"
    # older games' quotes came from the Odds API
    assert PL.pick_market([], [{**r, "provider": "odds_api"} for r in api])[1] == "odds_api"
    assert PL.pick_market(None, None) == (None, None, None)


def S_row(row: dict):
    """A prop snapshot as the logger reads it (attribute access)."""
    from types import SimpleNamespace
    return SimpleNamespace(**row, captured_at=NOW - 2 * H)


# ---------- log + score end to end ----------

class FakePredict:
    async def get_upcoming_game_prediction(self, game, db):
        return [0.6, 0.4]

    async def predict_skater(self, db, pid, team, game):
        return {"goals": 0.3, "shots_on_goal": 3.4, "prob_goals": 0.26}

    async def predict_goalie(self, db, pid, team, game):
        return {"goals_against": 2.9, "saves": 26.0}


@pytest.fixture
def fake_models(monkeypatch):
    import predictions.predict as P
    fake = FakePredict()
    for name in ("get_upcoming_game_prediction", "predict_skater", "predict_goalie"):
        monkeypatch.setattr(P, name, getattr(fake, name))
    monkeypatch.setattr(PL, "model_version", lambda: "v-test")


async def seed(db):
    db.add_all([Team(tri_code=t, current_name=t, franchise_id=i, last_updated=NOW) for i, t in enumerate(("TOR", "MTL"))])
    db.add_all([Player(id=1, first_name="A", last_name="S", position="C", current_team_tri_code="TOR", last_updated=NOW),
                Player(id=2, first_name="B", last_name="G", position="G", current_team_tri_code="MTL", last_updated=NOW)])
    db.add_all([game(1, NOW + 2 * H, "FUT"), game(2, NOW - H, "LIVE")])
    await db.commit()
    await S.insert_game_odds_snapshots(db, [odds_row(1, -110, -110, 0.55)], NOW - H)
    await S.insert_player_prop_snapshots(db, [prop_row(1), prop_row(1, pid=2, prop="saves", line=25.5, over=-110, under=-110)], NOW - H)


def test_log_is_idempotent_and_never_overwrites(fake_models):
    async def go(db):
        await seed(db)
        first = await PL.log_predictions(db, game_date=20261008, now=NOW)
        again = await PL.log_predictions(db, game_date=20261008, now=NOW + datetime.timedelta(minutes=20))   # same hour
        later = await PL.log_predictions(db, game_date=20261008, now=NOW + H)    # later run (e.g. the 22:00 retry)
        team = (await db.execute(select(PredictionLog).order_by(PredictionLog.id))).scalars().all()
        players = (await db.execute(select(PlayerPredictionLog))).scalars().all()
        return first, again, later, team, players
    first, again, later, team, players = run(go)
    assert first["games"] == 1 and first["team_rows"] == 1 and first["player_rows"] == 4   # live game 2 skipped
    assert again["skipped_logged"] == 1 and again["team_rows"] == 0
    # one frozen log per game per model version: a later run of the same model doesn't log the game again
    assert later["skipped_logged"] == 1 and later["team_rows"] == 0 and len(team) == 1
    t = team[0]
    assert t.home_win_prob == 0.6 and t.market_home_prob_novig == 0.55 and t.market_home_moneyline == -110
    sog = next(p for p in players if p.stat == "shots_on_goal" and p.run_id == first["run_id"])
    assert sog.market_line == 2.5 and sog.market_n_books == 1 and sog.market_over_price == -120
    assert not any(p.stat.startswith("prob_") for p in players)
    assert next(p for p in players if p.stat == "goals").market_line is None   # no goals market posted


def test_score_predictions_end_to_end(fake_models):
    async def go(db):
        await seed(db)
        await PL.log_predictions(db, game_date=20261008, now=NOW)
        # the game finishes; nightly fetch writes the frozen close
        g = await db.get(Games, 1)
        g.game_state, g.home_score, g.away_score = "OFF", 3, 2
        await db.commit()
        later = NOW + 8 * H
        await S.insert_game_odds_snapshots(db, [odds_row(1, -130, 110, 0.58)], later)
        await S.insert_player_prop_snapshots(db, [prop_row(1, over=-135, under=110)], later)
        db.add(SkaterGameLog(game_id=1, player_id=1, name="A S", season=2026, player_team_tricode="TOR",
                             opposing_team_tricode="MTL", game_date=20261008, goals=1, primary_assists=0,
                             secondary_assists=0, points=1, x_goals=0.4, toi=1000, high_danger_shots=1,
                             shot_attempts=6, on_ice_x_goals_percentage=0.5, game_score=1.0, shots_on_goal=4,
                             last_updated=NOW))
        await db.commit()
        first = await PL.score_predictions(db, now=later)
        second = await PL.score_predictions(db, now=later)
        scores = {(s.kind, s.stat): s for s in (await db.execute(select(PredictionScore))).scalars().all()}
        report = await PL.model_report(db)
        return first, second, scores, report
    first, second, scores, report = run(go)
    assert first["team_scored"] == 1 and second == {"player_waiting_logs": 2}
    team = scores[("team", "home_win")]
    assert team.outcome == 1 and team.bet_side == "home" and team.clv_prob == pytest.approx(0.03)
    sog = scores[("player", "shots_on_goal")]
    assert sog.actual == 4 and sog.outcome == 1 and sog.market_prob_close > sog.market_prob_logged
    assert scores[("player", "goals")].status == "no_line"
    # goalie 2 has no goalie log for game 1 and no goalie logs exist for the game yet -> waits
    assert ("player", "saves") not in scores and first["player_waiting_logs"] == 2
    assert report["groups"]["team"]["n"] == 1 and report["groups"]["team"]["bets"]["n"] == 1
    assert report["groups"]["player:shots_on_goal"]["vs_market_close"]["n"] == 1


def test_propline_fallback_logged_scored_and_reported(fake_models):
    async def go(db):
        await seed(db)
        # ESPN has no goals line for player 1; two consensus books on PropLine do (fetched before the log), and
        # Bovada, which is stored but not counted
        db.add_all([PropQuote(**quote(1, side=side, odds=odds, book=book, first=NOW - 2 * H))
                    for book in ("draftkings", "fanduel", "bovada") for side, odds in (("Over", 200), ("Under", -250))])
        await db.commit()
        await PL.log_predictions(db, game_date=20261008, now=NOW)
        players = {p.stat: p for p in (await db.execute(select(PlayerPredictionLog))).scalars().all()}
        # a later fetch before puck drop moves draftkings toward the over (upsert: latest price, new last_seen)
        for q in (await db.execute(select(PropQuote).where(PropQuote.bookmaker == "draftkings"))).scalars():
            q.odds, q.last_seen = (170 if q.over_under == "Over" else -210), NOW + H
        g = await db.get(Games, 1)
        g.game_state, g.home_score, g.away_score = "OFF", 3, 2
        await db.commit()
        later = NOW + 8 * H
        db.add(SkaterGameLog(game_id=1, player_id=1, name="A S", season=2026, player_team_tricode="TOR",
                             opposing_team_tricode="MTL", game_date=20261008, goals=1, primary_assists=0,
                             secondary_assists=0, points=1, x_goals=0.4, toi=1000, high_danger_shots=1,
                             shot_attempts=6, on_ice_x_goals_percentage=0.5, game_score=1.0, shots_on_goal=4,
                             last_updated=NOW))
        await db.commit()
        # each row scored against its own feed's close (ESPN: its last pre-game capture; PropLine: the later fetch)
        first = await PL.score_predictions(db, now=later)
        scores = {s.stat: s for s in (await db.execute(select(PredictionScore))).scalars().all()}
        report = await PL.model_report(db)
        return players, first, scores, report
    players, first, scores, report = run(go)
    goals, sog = players["goals"], players["shots_on_goal"]
    assert goals.market_source == "propline" and goals.market_line == 0.5 and goals.market_n_books == 2
    assert goals.market_over_price == 200 and goals.market_captured_at.replace(tzinfo=datetime.timezone.utc) == NOW - 2 * H
    assert sog.market_source == "espn" and players["saves"].market_source == "espn"
    assert first["player_scored"] == 2
    g = scores["goals"]
    assert g.status == "scored" and g.outcome == 1 and g.market_prob_close > g.market_prob_logged
    # the ESPN row's close is ESPN's (unchanged), not PropLine's
    assert scores["shots_on_goal"].market_prob_close == pytest.approx(scores["shots_on_goal"].market_prob_logged)
    assert report["player_by_source"]["goals"]["propline"]["vs_market_close"]["n"] == 1
    cov = report["coverage"]
    assert cov["rows"] == 3 and cov["games"] == 1        # goals, shots_on_goal, saves (goals_against is unpriced)
    assert cov["stats"]["goals"]["propline"] == {"n": 1, "share": 1.0}
    assert cov["stats"]["shots_on_goal"]["espn"]["n"] == 1 and cov["stats"]["saves"]["espn"]["n"] == 1
    assert cov["games_with_line"] == {"espn": 1, "propline": 1, "odds_api": 0} and cov["games_without_any_line"] == 0
    assert "goals_against" not in cov["stats"]          # unpriced stats aren't counted
