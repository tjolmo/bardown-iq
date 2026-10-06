import asyncio
import datetime
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, Games, GameOdds
from app.crud.game_odds import game_odds_upsert_stmt, get_game_odds, get_games_for_odds_matching
from external.espn.game_odds import build_game_odds_rows

NOW = datetime.datetime(2025, 10, 8, 23, 0, tzinfo=datetime.timezone.utc)


def event(eid, date, home, away, status="STATUS_FINAL"):
    return {"espn_event_id": eid, "date": date, "home_team": home, "away_team": away,
            "status": status, "completed": True, "season_type": "regular"}


def book(provider, home_ml, away_ml, valid=True, live=False, total=6.5):
    from external.espn.odds import devig
    hp, ap, ov = devig(home_ml, away_ml)
    return {"provider": provider, "is_live": live, "valid_2way": valid, "home_ml": home_ml, "away_ml": away_ml,
            "overround": ov, "home_prob": hp if valid else None, "away_prob": ap if valid else None,
            "total": total, "open_home_prob": None, "open_total": None}


GAMES = [
    {"id": 2025020001, "date": 20251008, "home_team_tri_code": "TOR", "away_team_tri_code": "MTL"},
    {"id": 2025020002, "date": 20251008, "home_team_tri_code": "BOS", "away_team_tri_code": "CHI"},
    {"id": 2025020003, "date": 20251009, "home_team_tri_code": "EDM", "away_team_tri_code": "CGY"},
]


def test_rows_only_for_matched_games_with_a_price():
    events = [
        event("1", 20251008, "TOR", "MTL"),
        event("2", 20251008, "BOS", "CHI"),         # matched, but only a 3-way book -> dropped
        event("3", 20251010, "EDM", "CGY"),         # ESPN a day late -> matched on date-1, NHL date kept
        event("4", 20251008, "NYR", "NJD"),         # no NHL game -> dropped
        event("5", 20251008, None, "MTL"),          # All-Star / exhibition -> dropped
    ]
    books = {
        "1": [book("A", -150, 130), book("B", -140, 120), book("Live", -400, 300, live=True)],
        "2": [book("Bet365", 145, 145, valid=False)],
        "3": [book("A", 110, -130)],
        "4": [book("A", -110, -110)],
        "5": [book("A", -110, -110)],
    }
    rows = {r["game_id"]: r for r in build_game_odds_rows(events, books, GAMES)}
    assert set(rows) == {2025020001, 2025020003}
    tor = rows[2025020001]
    assert tor["n_books"] == 2 and tor["books"] == "A|B"
    assert tor["home_moneyline"] == -145 and tor["espn_event_id"] == 1
    assert 0.5 < tor["home_prob_novig"] < 0.6
    assert (tor["home_team_tri_code"], tor["away_team_tri_code"], tor["total_line"]) == ("TOR", "MTL", 6.5)
    assert rows[2025020003]["date"] == 20251009


def test_failed_odds_fetch_is_skipped():
    assert build_game_odds_rows([event("1", 20251008, "TOR", "MTL")], {"1": None}, GAMES) == []


def test_upsert_statement_shape():
    rows = [{"game_id": 1, "date": 20251008, "home_team_tri_code": "TOR", "away_team_tri_code": "MTL",
             "home_prob_novig": 0.55, "n_books": 1, "extra": "ignored"}]
    sql = str(game_odds_upsert_stmt(rows).compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (game_id) DO UPDATE" in sql
    for col in ("home_prob_novig", "open_home_prob_novig", "total_line", "books", "espn_event_id"):
        assert f"{col} = excluded.{col}" in sql
    assert "last_updated = %(param_1)s" in sql  # refreshed to now on every upsert
    assert "game_id = excluded.game_id" not in sql and "extra" not in sql


def test_db_loaders():
    async def go():
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine)() as db:
            for g in GAMES:
                db.add(Games(**g, season=20252026, venue="v", start_time=NOW, game_state="OFF", last_updated=NOW))
            db.add(GameOdds(game_id=2025020001, date=20251008, home_team_tri_code="TOR", away_team_tri_code="MTL",
                            home_prob_novig=0.55, n_books=2, last_updated=NOW))
            await db.commit()
            games = await get_games_for_odds_matching(db, 20251008, 20251008)
            odds_all = await get_game_odds(db)
            odds_none = await get_game_odds(db, [2025020002])
            return games, odds_all, odds_none
    games, odds_all, odds_none = asyncio.run(go())
    assert sorted(g["id"] for g in games) == [2025020001, 2025020002]
    assert set(games[0]) == {"id", "date", "home_team_tri_code", "away_team_tri_code"}
    assert [o.game_id for o in odds_all] == [2025020001] and odds_none == []
