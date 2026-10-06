from predictions.train import train_team_classifiers, train_goalie_models, train_skater_classifiers, train_skater_models
from app.crud.props import upsert_player_props
from app.schemas.player import PlayerPropOut
from app.crud.players import get_player_by_name_and_roster_options
from app.crud.teams import search_teams_by_name
from app.crud.games import get_all_games_for_date
from external.odds_api.dedupe import select_best_props
from external.odds_api.player_props import get_upcoming_games_odds_api, get_player_props
from app.crud.goalie_game_features import update_goalie_game_features
from app.crud.skater_game_features import update_skater_game_features
from external.moneypuck.player import scrape_all_goalie_game_logs, scrape_all_skater_game_logs
from external.nhl.players import fetch_and_get_players_info
from external.nhl.teams import fetch_and_clean_team, fetch_and_clean_team_roster, fetch_and_clean_team_schedule
from external.nhl.games import fetch_and_get_players_in_a_game, get_current_scores
from .crud.team_history import upsert_team_history, check_team_history_exists_and_updated
from .crud.teams import get_all_tri_codes_in_db, upsert_team,update_team_roster_last_updated, get_all_tri_codes_update_roster
from .crud.games import has_games_to_poll, check_if_games_in_db, upsert_scraped_games_from_schedule, get_date_most_recent_game_marked_as_future, delete_games_for_team_in_the_future
from .crud.players import get_players_not_in_db, upsert_scraped_player, set_all_other_players_current_team_tri_code_to_null
from .crud.skater_game_logs import upsert_scraped_game_logs
from .crud.goalie_game_logs import upsert_scraped_goalie_game_logs
from app.database import AsyncSessionLocal
from app.crud.team_game_logs import build_team_game_logs
from app.crud.team_game_features import update_team_game_features
import asyncio
import datetime

CURRENT_TEAMS = [
        8, 7, 2, 28, 13, 12, 54, 52, 
        18, 1, 9, 21, 15, 26, 10, 22,
        20, 19, 17, 3, 24, 23, 16, 55, 
        5, 6, 25, 14, 4, 30, 68, 29, 53 #ari
]
OLD_TEAMS = [59] #uhc

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

async def add_old_teams_to_db():
    async with AsyncSessionLocal() as db:
        for team_id in OLD_TEAMS:
            if not await check_team_history_exists_and_updated(db, team_id):
                _, team_history_data = await fetch_and_clean_team(team_id)
                if team_history_data:
                    await upsert_team_history(db, team_history_data)
            else:
                print(f"Team history for team ID {team_id} already exists in DB, skipping.")

async def fetch_current_rosters_for_all_teams():
    async with AsyncSessionLocal() as db:
        tri_codes = await get_all_tri_codes_update_roster(db)
        for tri_code in tri_codes:
            roster_data = await fetch_and_clean_team_roster(tri_code, "current")
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
        for tri_code in tri_codes:
            current_marked_upcoming_date = await get_date_most_recent_game_marked_as_future(db, tri_code)
            # only fetch and update if current time(UTC) more recent
            current_time = datetime.datetime.now(datetime.timezone.utc)
            if current_marked_upcoming_date is None or current_time >= current_marked_upcoming_date:
                schedule_data = await fetch_and_clean_team_schedule(tri_code, "now")
                if schedule_data:
                    # remove all games in database for this team that are in the future
                    await delete_games_for_team_in_the_future(db, tri_code)
                    # upsert all games
                    await upsert_scraped_games_from_schedule(db, schedule_data)

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

async def update_daily_features():
    async with AsyncSessionLocal() as db:
        await update_skater_game_features(db)
        await update_goalie_game_features(db)
        await build_team_game_logs(db)
        await update_team_game_features(db)

def get_current_season_start_year(today: datetime.date | None = None) -> int:
    """Start year of the NHL season in progress (MoneyPuck's `season` value), e.g. 2025 for 2025-26.
    The season rolls over on Sept 1, after the prior season's playoffs end and before preseason."""
    today = today or datetime.date.today()
    return today.year if today.month >= 9 else today.year - 1

async def add_missing_players(db, player_ids: set[int]) -> set[int]:
    """Fetches and stores players not yet in the DB. Returns the ids whose info could not be fetched."""
    failed: set[int] = set()
    for player_id in await get_players_not_in_db(db, list(player_ids)):
        player_info = await fetch_and_get_players_info(player_id)
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
        #match to games in db
        for event in events:
            home_team_in_db = await search_teams_by_name(db, event.home_team, 1)
            away_team_in_db = await search_teams_by_name(db, event.away_team, 1)
            potential_tri_codes = []

            home_tri_code = None
            if home_team_in_db:
                home_tri_code = home_team_in_db[0].tri_code
                potential_tri_codes.append(home_tri_code)
            away_tri_code = None
            if away_team_in_db:
                away_tri_code = away_team_in_db[0].tri_code
                potential_tri_codes.append(away_tri_code)
            
            if len(potential_tri_codes) == 0:
                print(f"No team found for event {event.event_id}")
                continue

            game_id = None
            for game in all_games_today:
                if game.home_team_tri_code == home_tri_code and game.away_team_tri_code == away_tri_code:
                    game_id = game.id
                    break
            if game_id is None:
                print(f"No game found for event {event.event_id}")
                continue

            player_props = await get_player_props(event.event_id)
            props_to_upsert = []
            for prop in player_props:
                player = await get_player_by_name_and_roster_options(db, prop.first_name, prop.last_name, potential_tri_codes)
                if player is None:
                    print(f"No player found for prop {prop.first_name} {prop.last_name}")
                    continue
                props_to_upsert.append(PlayerPropOut(
                    game_id=game_id,
                    player_id=player.id,
                    prop_type=prop.prop_type,
                    over_under=prop.over_under,
                    odds=prop.odds,
                    line=prop.line
                ))
            
            if len(props_to_upsert) > 0:
                # same prop from several bookmakers: keep consensus line at the best price
                await upsert_player_props(db, select_best_props(props_to_upsert))
                
async def train_models():
    async with AsyncSessionLocal() as db:
        await train_skater_models(db)
        await train_skater_classifiers(db)
        await train_goalie_models(db)
        await train_team_classifiers(db)
