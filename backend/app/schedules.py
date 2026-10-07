from predictions.train import train_all_models
from app.crud.props import upsert_player_props
from app.crud.odds_api_prop_quotes import upsert_odds_api_prop_quotes
from app.schemas.player import PlayerPropOut
from app.crud.players import get_players_on_teams
from app.player_matching import index_players_by_name, match_player
from app.crud.teams import get_all_teams
from app.name_matching import normalize_name
from app.crud.games import get_all_games_for_date
from external.odds_api.dedupe import select_best_props
from external.odds_api.player_props import get_upcoming_games_odds_api, get_player_props
from external.moneypuck.player import scrape_all_goalie_game_logs, scrape_all_skater_game_logs
from external.moneypuck.teams import scrape_team_game_stats
from app.crud.team_game_stats import upsert_team_game_stats
from external.nhl.players import fetch_and_get_players_info
from external.nhl.teams import fetch_and_clean_team, fetch_and_clean_team_roster, fetch_and_clean_team_schedule
from external.nhl.games import fetch_and_get_players_in_a_game, get_current_scores
from external.nhl.response_models import GameResponse
from .crud.team_history import upsert_team_history, check_team_history_exists_and_updated
from .crud.teams import get_all_tri_codes_in_db, upsert_team,update_team_roster_last_updated, get_all_tri_codes_update_roster
from .crud.games import FINISHED_GAME_STATES, has_games_to_poll, check_if_games_in_db, upsert_scraped_games_from_schedule, delete_future_games_not_in
from .crud.players import get_players_not_in_db, upsert_scraped_player, set_all_other_players_current_team_tri_code_to_null
from .crud.skater_game_logs import upsert_scraped_game_logs
from .crud.goalie_game_logs import upsert_scraped_goalie_game_logs
from .crud.game_odds import upsert_game_odds, get_games_for_odds_matching
from external.espn.game_odds import fetch_game_odds
from .crud.player_prop_odds import upsert_player_prop_odds, get_known_athlete_ids, get_player_match_data
from .crud.odds_snapshots import insert_game_odds_snapshots, insert_player_prop_snapshots
from external.espn.props import fetch_player_prop_odds
from external.espn.player_ids import build_player_index
from app.database import AsyncSessionLocal
import asyncio
from external.http import gather_bounded
import datetime

CURRENT_TEAMS = [
        8, 7, 2, 28, 13, 12, 54, 52, 
        18, 1, 9, 21, 15, 26, 10, 22,
        20, 19, 17, 3, 24, 23, 16, 55, 
        5, 6, 25, 14, 4, 30, 68, 29, 53 #ari
]
OLD_TEAMS = [59] #uhc
# relocated teams whose old tri codes appear in 2008-2014 games/logs; only needed for historical backfills
HISTORICAL_TEAMS = [11, 27] #atl, phx

async def add_current_teams_to_db():
    async with AsyncSessionLocal() as db:
        for team_id in CURRENT_TEAMS:
            if not await check_team_history_exists_and_updated(db, team_id):
                team_data, team_history_data = await fetch_and_clean_team(team_id)
                if team_data and team_history_data:
                    await upsert_team(db, team_data)
                    await upsert_team_history(db, team_history_data)
            else:
                print(f"Team history for team ID {team_id} already exists in DB, skipping.")

async def add_old_teams_to_db(team_ids: list[int] = OLD_TEAMS):
    async with AsyncSessionLocal() as db:
        tri_codes = set(await get_all_tri_codes_in_db(db))
        for team_id in team_ids:
            if not await check_team_history_exists_and_updated(db, team_id):
                team = await fetch_and_clean_team(team_id)
                if team:
                    team_data, team_history_data = team
                    # a tri code no current team uses (e.g. ATL) needs its own teams row for the FKs
                    if team_data.tri_code not in tri_codes:
                        await upsert_team(db, team_data)
                    await upsert_team_history(db, team_history_data)
            else:
                print(f"Team history for team ID {team_id} already exists in DB, skipping.")

async def fetch_current_rosters_for_all_teams():
    async with AsyncSessionLocal() as db:
        tri_codes = await get_all_tri_codes_update_roster(db)
        # fetch all rosters concurrently; DB writes stay sequential (one session)
        rosters = await gather_bounded([fetch_and_clean_team_roster(tri_code, "current") for tri_code in tri_codes])
        for tri_code, roster_data in zip(tri_codes, rosters):
            if roster_data:
                for player in roster_data:
                    await upsert_scraped_player(db, player, tri_code)
                # only clear players previously on this team who are no longer on its roster
                await set_all_other_players_current_team_tri_code_to_null(
                    db, tri_code, [player.id for player in roster_data]
                )
                await update_team_roster_last_updated(db, tri_code)
        
async def fetch_current_schedules_for_all_teams():
    async with AsyncSessionLocal() as db:
        tri_codes = await get_all_tri_codes_in_db(db)
        # fetch all team schedules concurrently, then write sequentially (one session)
        # Always refetch: postponements, new start times and newly added games are only visible in the fetched schedule.
        schedules = await gather_bounded([fetch_and_clean_team_schedule(tri_code, "now") for tri_code in tri_codes])
        for tri_code, schedule_data in zip(tri_codes, schedules):
            if schedule_data:
                # upsert first so a failed fetch/insert never leaves the team without games
                await upsert_scraped_games_from_schedule(db, schedule_data)
                # then drop only future games the NHL no longer lists (cancellations)
                await delete_future_games_not_in(db, tri_code, [game.id for game in schedule_data])

async def fetch_all_season_schedules_for_all_teams():
    async with AsyncSessionLocal() as db:
        tri_codes = await get_all_tri_codes_in_db(db)
        for season in ["20202021", "20212022", "20222023", "20232024", "20242025", "now"]:
            all_schedule_data = set()
            for tri_code in tri_codes:
                schedule_data = await fetch_and_clean_team_schedule(tri_code, season)
                if schedule_data:
                    all_schedule_data.update(schedule_data)
            # once all schedules fetched, process
            all_players_in_season = set()
            # limit to games not in db already
            games_in_db = await check_if_games_in_db(db, [game.id for game in all_schedule_data])
            schedule_data_to_add = [game for game in all_schedule_data if game.id not in games_in_db]

            for game in schedule_data_to_add:
                # fetch players in game, 
                players_in_game = await fetch_and_get_players_in_a_game(game.id)
                if players_in_game:
                    all_players_in_season.update(players_in_game)

            # check which players not in db, fetch info for those players and add to db
            if all_players_in_season:
                players_not_in_db = await get_players_not_in_db(db, list(all_players_in_season))
                for player_id in players_not_in_db:
                    player_info = await fetch_and_get_players_info(player_id)
                    if player_info:
                        await upsert_scraped_player(db, player_info, None)
        
            # add every game to db after player scrape to ensure that players added first
            if schedule_data_to_add:
                await upsert_scraped_games_from_schedule(db, schedule_data_to_add)

def is_regular_or_playoff_game(game_id: int) -> bool:
    """Game type is digits 5-6 of an NHL game id: 02 regular season, 03 playoffs."""
    return game_id // 10_000 % 100 in (2, 3)

def merge_season_schedules(schedules: list[list[GameResponse] | None]) -> list[GameResponse]:
    """Dedupes team schedules (each game appears in both teams' schedules) into regular season and playoff games,
    marking finished games OFF so they match the rest of the table."""
    games = {}
    for schedule in schedules:
        for game in schedule or []:
            if is_regular_or_playoff_game(game.id):
                if game.game_state in FINISHED_GAME_STATES:
                    game = game.model_copy(update={"game_state": "OFF"})
                games[game.id] = game
    return sorted(games.values(), key=lambda game: game.id)

async def backfill_season_games(season_start_years: list[int]):
    """Upserts schedules and final scores for past seasons (start years, e.g. 2008 for 2008-09).
    Unlike fetch_all_season_schedules_for_all_teams it does not fetch the players in each game."""
    async with AsyncSessionLocal() as db:
        # teams with no games that season (expansion/relocated) just return an empty schedule
        tri_codes = await get_all_tri_codes_in_db(db)
        for year in season_start_years:
            season = f"{year}{year + 1}"
            schedules = await gather_bounded([fetch_and_clean_team_schedule(tri_code, season) for tri_code in tri_codes])
            games = merge_season_schedules(schedules)
            await upsert_scraped_games_from_schedule(db, games)
            print(f"Season {season}: upserted {len(games)} games")

def get_current_season_start_year(today: datetime.date | None = None) -> int:
    """Start year of the NHL season in progress (MoneyPuck's `season` value), e.g. 2025 for 2025-26.
    The season rolls over on Sept 1, after the prior season's playoffs end and before preseason."""
    today = today or datetime.date.today()
    return today.year if today.month >= 9 else today.year - 1

async def add_missing_players(db, player_ids: set[int]) -> set[int]:
    """Fetches and stores players not yet in the DB. Returns the ids whose info could not be fetched."""
    failed: set[int] = set()
    missing_ids = await get_players_not_in_db(db, list(player_ids))
    # fetch concurrently; DB writes stay sequential (one session)
    player_infos = await gather_bounded([fetch_and_get_players_info(player_id) for player_id in missing_ids])
    for player_id, player_info in zip(missing_ids, player_infos):
        if player_info:
            await upsert_scraped_player(db, player_info, None)
        else:
            failed.add(player_id)
    if failed:
        print(f"Could not fetch info for {len(failed)} players; skipping their game logs: {sorted(failed)}")
    return failed

async def scrape_all_player_logs(seasons: list[int] | None = None):
    # resolve at run time so a long-running scheduler follows the calendar
    if seasons is None:
        seasons = [get_current_season_start_year()]
    async with AsyncSessionLocal() as db:
        for season in seasons:
            # blocking download + pandas parse, so keep it off the event loop
            all_skaters = await asyncio.to_thread(scrape_all_skater_game_logs, season)
            if all_skaters:
                unplaceable = await add_missing_players(db, {skater.player_id for skater in all_skaters})
                # drop logs for players we couldn't fetch (single pass)
                all_skaters = [skater for skater in all_skaters if skater.player_id not in unplaceable]
                await upsert_scraped_game_logs(db, all_skaters)
            all_goalies = await asyncio.to_thread(scrape_all_goalie_game_logs, season)
            if all_goalies:
                unplaceable = await add_missing_players(db, {goalie.player_id for goalie in all_goalies})
                all_goalies = [goalie for goalie in all_goalies if goalie.player_id not in unplaceable]
                await upsert_scraped_goalie_game_logs(db, all_goalies)

async def scrape_team_stats(seasons: list[int] | None = None):
    """Team game totals by situation (all, 5v5, PP, PK) from MoneyPuck; the team model's strength features."""
    if seasons is None:
        seasons = [get_current_season_start_year()]
    rows = await asyncio.to_thread(scrape_team_game_stats, seasons)
    if rows is None:
        raise RuntimeError("MoneyPuck team stats download failed")
    async with AsyncSessionLocal() as db:
        await upsert_team_game_stats(db, rows)

async def fetch_current_scores():
    async with AsyncSessionLocal() as db:
        # the job fires every 10 minutes, but only hit the NHL API around games
        if not await has_games_to_poll(db):
            return
        tri_codes = set(await get_all_tri_codes_in_db(db))
        scores = await get_current_scores(tri_codes)
        await upsert_scraped_games_from_schedule(db, scores)

async def fetch_current_player_props():
    start_time = datetime.datetime.now(datetime.timezone.utc)
    end_time = start_time + datetime.timedelta(days=1)
    int_date = int(start_time.strftime("%Y%m%d"))
    async with AsyncSessionLocal() as db:
        events = await get_upcoming_games_odds_api(start_time, end_time)
        all_games_today = await get_all_games_for_date(db, int_date)
        # match Odds API team names to tri codes ignoring accents/case/punctuation ("Montreal" vs "Montréal")
        tri_codes_by_name = {normalize_name(team.current_name): team.tri_code for team in await get_all_teams(db)}
        #match to games in db
        for event in events:
            home_tri_code = tri_codes_by_name.get(normalize_name(event.home_team))
            away_tri_code = tri_codes_by_name.get(normalize_name(event.away_team))
            potential_tri_codes = [code for code in (home_tri_code, away_tri_code) if code]

            if len(potential_tri_codes) == 0:
                print(f"No team found for event {event.event_id} ({event.away_team} @ {event.home_team})")
                continue

            game_id = None
            for game in all_games_today:
                if game.home_team_tri_code == home_tri_code and game.away_team_tri_code == away_tri_code:
                    game_id = game.id
                    break
            if game_id is None:
                print(f"No game found for event {event.event_id}")
                continue

            try:
                player_props = await get_player_props(event.event_id)
                players_by_name = index_players_by_name(await get_players_on_teams(db, potential_tri_codes))
                props_to_upsert = []
                quotes = []
                unmatched = {}
                for prop in player_props:
                    player, reason = match_player(players_by_name, prop.first_name, prop.last_name, prop.prop_type)
                    if player is None:
                        unmatched[f"{prop.first_name} {prop.last_name}"] = reason
                        continue
                    quotes.append({"game_id": game_id, "player_id": player.id, "prop_type": prop.prop_type,
                                   "over_under": prop.over_under, "line": prop.line, "odds": prop.odds,
                                   "bookmaker": prop.bookmaker, "book_last_update": prop.book_last_update,
                                   "event_id": event.event_id})
                    props_to_upsert.append(PlayerPropOut(
                        game_id=game_id,
                        player_id=player.id,
                        prop_type=prop.prop_type,
                        over_under=prop.over_under,
                        odds=prop.odds,
                        line=prop.line
                    ))
                if unmatched:
                    print(f"Event {event.event_id}: {len(unmatched)} players not matched: {unmatched}")

                if len(props_to_upsert) > 0:
                    # same prop from several bookmakers: keep consensus line at the best price
                    await upsert_player_props(db, select_best_props(props_to_upsert))
                    # and every book's own quote, for line-shopping / consensus backtests later; props are already
                    # committed, so a failure here only loses the quotes
                    try:
                        await upsert_odds_api_prop_quotes(db, quotes)
                    except Exception as e:
                        await db.rollback()
                        print(f"Saved props but failed to store quotes for event {event.event_id}: {e}")
            except Exception as e:
                # one bad event must not stop props for the remaining games
                await db.rollback()
                print(f"Failed to process props for event {event.event_id}: {e}")

async def train_models():
    # features are built from the game logs inside training, so there is no separate feature step
    async with AsyncSessionLocal() as db:
        await train_all_models(db)


async def refresh_skater_shares():
    """Per-game deployment shares of every game whose logs may have changed (predictions/shares.py), so live skater
    predictions read them instead of every teammate's logs. Mirrors whatever the logs hold, so it runs even after a
    failed scrape."""
    from predictions.shares import refresh_skater_shares as refresh
    async with AsyncSessionLocal() as db:
        print(f"Skater shares: {await refresh(db)}")


async def append_snapshots(name: str, insert_fn, db, rows: list[dict]) -> int:
    """Writes odds snapshots; a failure only loses this run's snapshots, never the current/opening tables."""
    try:
        return await insert_fn(db, rows)
    except Exception as e:
        await db.rollback()
        print(f"Failed to store {name} snapshots: {e!r}")
        return 0


async def fetch_game_odds_for_range(start: datetime.date, end: datetime.date, cache_dir: str | None = None) -> int:
    """Fetches ESPN closing odds for start..end, matches them to games in the DB and upserts them."""
    def yyyymmdd(d: datetime.date) -> int:
        return int(d.strftime("%Y%m%d"))
    async with AsyncSessionLocal() as db:
        # one day of slack on each side for ESPN events matched on a shifted date
        games = await get_games_for_odds_matching(db, yyyymmdd(start - datetime.timedelta(days=1)), yyyymmdd(end + datetime.timedelta(days=1)))
        # blocking threaded HTTP, so keep it off the event loop
        rows, client = await asyncio.to_thread(fetch_game_odds, start, end, games, cache_dir)
        await upsert_game_odds(db, rows)
        # append-only price path (pre-game prices, plus the frozen close once a game is final)
        snapshots = await append_snapshots("game odds", insert_game_odds_snapshots, db, rows)
    print(f"Game odds {start}..{end}: upserted {len(rows)} games, {snapshots} snapshots ({client.fetched} network fetches)")
    return len(rows)

async def fetch_recent_game_odds(days: int = 3):
    """Closing lines for the last few days plus today's upcoming games (overwritten with closing lines later)."""
    today = datetime.date.today()
    await fetch_game_odds_for_range(today - datetime.timedelta(days=days), today)


async def fetch_player_prop_odds_for_range(start: datetime.date, end: datetime.date, cache_dir: str | None = None) -> int:
    """Fetches ESPN player props for start..end, maps ESPN athletes to NHL players and upserts player_prop_odds."""
    def yyyymmdd(d: datetime.date) -> int:
        return int(d.strftime("%Y%m%d"))
    async with AsyncSessionLocal() as db:
        games = await get_games_for_odds_matching(db, yyyymmdd(start - datetime.timedelta(days=1)), yyyymmdd(end + datetime.timedelta(days=1)))
        # a season of slack so early-season games can lean on last season's team logs
        players, team_seasons, game_players = await get_player_match_data(db, get_current_season_start_year(start) - 1)
        known = await get_known_athlete_ids(db)
        index = build_player_index(players, team_seasons, game_players)
        # blocking threaded HTTP, so keep it off the event loop
        rows, report = await asyncio.to_thread(fetch_player_prop_odds, start, end, games, index, known, cache_dir)
        await upsert_player_prop_odds(db, rows)
        snapshots = await append_snapshots("player prop", insert_player_prop_snapshots, db, rows)
    stats = report["stats"]
    print(f"Player props {start}..{end}: {stats['events_with_props']}/{report['events']} events with props, "
          f"upserted {len(rows)} markets ({snapshots} snapshots); athletes matched {report['athletes_matched']}/{report['athletes']}; "
          f"markets dropped: {stats['markets_unmatched_player']} unmatched player, {stats['markets_unmatched_game']} unmatched game; "
          f"{report['network_fetches']} network fetches")
    if report["unmatched"]:
        sample = sorted(report["unmatched"].items())[:25]
        print(f"Unmatched ESPN athletes ({len(report['unmatched'])}), sample: {sample}")
    return len(rows)

async def fetch_recent_player_prop_odds(days: int = 2):
    """Prices for the last few days' finished games (frozen at puck drop) plus today's and tomorrow's games.
    Player props only show up on game day, so today's pre-game prices need a daytime run to be captured."""
    today = datetime.date.today()
    await fetch_player_prop_odds_for_range(today - datetime.timedelta(days=days), today + datetime.timedelta(days=1))


async def run_step(name: str, step):
    """Runs one pipeline step; a failure is logged and the pipeline moves on to the next step."""
    try:
        await step()
    except Exception as e:
        print(f"Pipeline step '{name}' failed: {e!r}")
        return False
    return True

def current_game_day(now: datetime.datetime | None = None) -> datetime.date:
    """The North American game day: UTC shifted back 12 hours (as predictions.predict._today)."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return (now - datetime.timedelta(hours=12)).date()

async def fetch_confirmed_starters(days: int = 1, game_day: datetime.date | None = None) -> int:
    """Starting goalies for the next `days` game days' unfinished games into game_starters: confirmed/expected
    starters from ESPN, matched to NHL ids via the gamecenter rosters, or the goalie actually in net once a game
    has started (NHL play-by-play). Teams without either keep the model's projection. Returns rows written."""
    from external.espn.starters import fetch_probable_goalies, resolve_starters
    from external.nhl.games import fetch_game_goalies
    from .crud.game_starters import upsert_game_starters
    first = game_day or current_game_day()
    dates = [first + datetime.timedelta(days=i) for i in range(days)]
    async with AsyncSessionLocal() as db:
        games = [g for d in dates for g in await get_all_games_for_date(db, int(d.strftime("%Y%m%d")))
                 if g.game_state not in FINISHED_GAME_STATES]
        if not games:
            print(f"Starters: no unfinished games on {dates[0]}..{dates[-1]}")
            return 0
        picks = await fetch_probable_goalies(dates)
        rosters = await gather_bounded([fetch_game_goalies(g.id) for g in games])
        starters, problems = [], []
        for game, (goalies, pbp_starters) in zip(games, rosters):
            # the same matchup can be played on consecutive nights, so match ESPN events on start time too
            near = [p for p in picks if p["start"] is None or abs((p["start"] - game.start_time).total_seconds()) < 12 * 3600]
            found, issues = resolve_starters(game.id, game.home_team_tri_code, game.away_team_tri_code, near, goalies, pbp_starters)
            starters.extend(found)
            problems.extend(issues)
        written = await upsert_game_starters(db, starters)
    if written:
        # rebuild the cached prediction context on next use so it picks up the new starters
        from predictions import predict
        predict._context["built_at"] = 0.0
    counts = {status: sum(s.status == status for s in starters) for status in ("actual", "confirmed", "probable")}
    print(f"Starters: {written} team-games stored for {len(games)} games ({counts}); missing {len(problems)}: {problems[:10]}")
    return written

async def fetch_injury_report() -> int:
    """ESPN's league-wide injury report into player_injuries (one append-only snapshot per run), with ESPN athletes
    matched to NHL ids. Players it lists out / IR / suspended leave the expected lineups of upcoming games. If ESPN
    is down nothing is written and predictions keep using the last report (up to 36 hours old), then the previous
    game's lineups. Returns rows written."""
    from external.espn.injuries import fetch_injuries, match_injured_players
    from .crud.player_injuries import insert_injury_snapshot
    rows = await fetch_injuries()
    if rows is None:
        return 0
    async with AsyncSessionLocal() as db:
        players, _, _ = await get_player_match_data(db, get_current_season_start_year())
        rows, unmatched = match_injured_players(build_player_index(players), rows, await get_known_athlete_ids(db))
        written = await insert_injury_snapshot(db, rows)
    # rebuild the cached prediction context on next use so it picks up the new report
    from predictions import predict
    predict._context["built_at"] = 0.0
    statuses = {s: sum(r["status"] == s for r in rows) for s in sorted({r["status"] for r in rows})}
    # minor leaguers on ESPN's list are often not in the players table; they aren't in any lineup anyway
    print(f"Injuries: {written} listed players stored {statuses}; {len(unmatched)} not matched to NHL ids: "
          f"{sorted(unmatched.items())[:15]}")
    return written

async def record_actual_starters(game_ids: list[int], concurrency: int = 4) -> dict:
    """Who actually started each of `game_ids` (finished games): the goalie in net for the first shot each team faced
    (NHL play-by-play), else the boxscore's starter flag (see parse_actual_starters), stored in game_starters as source "nhl" / status "actual" (training
    uses these instead of the goalie with the most ice time, which names the reliever when a starter is pulled).
    Returns counts: games fetched/failed, teams found per method, teams missing and boxscore/pbp disagreements."""
    from external.nhl.games import fetch_actual_starters
    from .crud.game_starters import upsert_game_starters, actual_starter_rows
    results = await gather_bounded([fetch_actual_starters(gid) for gid in game_ids], limit=concurrency)
    rows, stats = [], {"games": len(game_ids), "failed": [], "boxscore": 0, "pbp": 0, "teams_missing": [], "disagree": []}
    for gid, res in zip(game_ids, results):
        if res is None:
            stats["failed"].append(gid)
            continue
        starters, method, disagree = res
        rows.extend(actual_starter_rows(gid, starters))
        for m in method.values():
            stats[m] += 1
        if len(starters) < 2:
            stats["teams_missing"].append(gid)
        stats["disagree"].extend((gid, team, box, pbp) for team, (box, pbp) in disagree.items())
    async with AsyncSessionLocal() as db:
        await upsert_game_starters(db, rows)
    return stats

async def fetch_recent_actual_starters(max_games: int = 400) -> int:
    """Actual starters for this season's finished games that don't have them yet (normally last night's games;
    a missed night is caught up on the next run). Returns team-games stored."""
    from .crud.game_starters import get_games_missing_actual_starters
    async with AsyncSessionLocal() as db:
        game_ids = await get_games_missing_actual_starters(db, min_season=get_current_season_start_year(), limit=max_games)
    if not game_ids:
        return 0
    stats = await record_actual_starters(game_ids)
    stored = stats["boxscore"] + stats["pbp"]
    print(f"Actual starters: {stored} team-games for {len(game_ids)} games (boxscore flag {stats['boxscore']}); "
          f"failed {stats['failed'][:10]}, incomplete {stats['teams_missing'][:10]}, boxscore/pbp disagree {stats['disagree'][:10]}")
    return stored

async def pregame_odds_pipeline():
    """Game lines and player props for today's games. ESPN posts player props only on game day, so the
    3am nightly run misses pre-game prices; this runs in the late afternoon (North American time).
    Starting goalies and the injury report go first so the predictions logged after them use the announced
    starters and drop injured players from the expected lineups."""
    await run_step("starting goalies", fetch_confirmed_starters)
    await run_step("injury report", fetch_injury_report)
    await run_step("game odds", fetch_recent_game_odds)
    await run_step("player prop odds", fetch_recent_player_prop_odds)
    # last: freezes today's predictions next to the market snapshot just fetched (forward test)
    await run_step("prediction log", log_todays_predictions)

async def morning_odds_pipeline():
    """A late-morning (ET) price snapshot, so the price path has an early point between the open and the
    afternoon log, and an injury report snapshot. Only ESPN (no metered Odds API calls)."""
    await run_step("injury report", fetch_injury_report)
    await run_step("game odds", fetch_recent_game_odds)
    await run_step("player prop odds", fetch_recent_player_prop_odds)

async def log_todays_predictions():
    from predictions.prediction_log import log_predictions
    async with AsyncSessionLocal() as db:
        print(f"Prediction log: {await log_predictions(db)}")

async def score_logged_predictions():
    from predictions.prediction_log import score_predictions
    async with AsyncSessionLocal() as db:
        print(f"Prediction scores: {await score_predictions(db)}")

async def nightly_pipeline():
    """Runs the nightly jobs in dependency order: schedules and rosters first (new games and players),
    then game logs (and the skater shares stored from them), then props (which need games and rosters), and finally
    training (which needs the fresh logs)."""
    await run_step("schedules", fetch_current_schedules_for_all_teams)
    await run_step("rosters", fetch_current_rosters_for_all_teams)
    logs_ok = await run_step("player logs", scrape_all_player_logs)
    logs_ok = await run_step("team stats", scrape_team_stats) and logs_ok
    await run_step("skater shares", refresh_skater_shares)
    if not logs_ok:
        # models trained on a partial log load would be wrong, so keep yesterday's models this run
        print("Skipping training: player log scrape failed")
    # who actually started last night's games (training labels the goalie model's rows and the starter features with these)
    await run_step("actual starters", fetch_recent_actual_starters)
    await run_step("game odds", fetch_recent_game_odds)
    await run_step("player prop odds", fetch_recent_player_prop_odds)
    # after the fetches above captured last night's closing prices and the logs scrape brought the box scores
    await run_step("prediction scoring", score_logged_predictions)
    await run_step("props", fetch_current_player_props)
    if logs_ok:
        await run_step("training", train_models)

async def full_refresh():
    """Refreshes everything: teams, schedules, rosters, game logs, live scores, props and models.
    Same ordering and skip rules as the nightly pipeline, plus the team tables the nightly run leaves alone."""
    await run_step("teams", add_current_teams_to_db)
    await run_step("old teams", add_old_teams_to_db)
    await run_step("schedules", fetch_current_schedules_for_all_teams)
    await run_step("rosters", fetch_current_rosters_for_all_teams)
    logs_ok = await run_step("player logs", scrape_all_player_logs)
    logs_ok = await run_step("team stats", scrape_team_stats) and logs_ok
    await run_step("skater shares", refresh_skater_shares)
    if not logs_ok:
        print("Skipping training: player log scrape failed")
    await run_step("scores", fetch_current_scores)
    await run_step("actual starters", fetch_recent_actual_starters)
    await run_step("game odds", fetch_recent_game_odds)
    await run_step("props", fetch_current_player_props)
    if logs_ok:
        await run_step("training", train_models)
