from app.crud.players import get_top_n_goalies
from app.crud.props import get_player_props_from_db
from app.schemas.teams import TeamRosteredPlayer
from app.crud.players import get_top_n_skaters
import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from app.crud.games import get_next_game_info_by_tri_code
from app.dependencies import get_db
from app.schemas.player import (GoalieLast5BasicStatsGetOut, GoalieSeasonBasicStatsGetOut, GoaliePredictionOut, PlayerGameLogGetOut, GoalieGameLogGetOut, 
                                PlayerNextGameGetOut, SkaterLast5BasicStatsGetOut, SkaterSeasonBasicStatsGetOut, PlayerBasicInfoOut, 
                                PlayerSearchResultOut, PlayerPredictionOut, PlayerPropOut)
from app.crud.players import get_player_by_id, search_players_by_name, get_player_current_team_tri_code
from app.crud.skater_game_logs import get_skater_last_5_basic_stats_from_db, get_player_game_log_by_game_and_player_id, get_skater_season_basic_stats_from_db
from app.crud.goalie_game_logs import get_goalie_last_5_basic_stats_from_db, get_goalie_season_basic_stats_from_db
from predictions.predict import predict_skater, predict_goalie

router = APIRouter(prefix="/players", tags=["players"])

@router.get("/get/skater/game_log/{game_id}/{player_id}", status_code=200, response_model=PlayerGameLogGetOut)
async def get_skater_game_log(game_id: int, player_id: int, db = Depends(get_db)):
    """Fetches a specific game log for a given player ID and game ID."""
    try:
        game_log = await get_player_game_log_by_game_and_player_id(db, game_id, player_id)
        if game_log:
            return game_log
        else:
            raise HTTPException(status_code=404, detail=f"Game log for player {player_id} and game {game_id} not found in DB")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving game log for player {player_id} and game {game_id} from DB: {e}")

@router.get("/get/goalie/game_log/{game_id}/{player_id}", status_code=200, response_model=GoalieGameLogGetOut)
async def get_player_game_log(game_id: int, player_id: int, db = Depends(get_db)):
    """Fetches a specific game log for a given player ID and game ID."""
    try:
        game_log = await get_player_game_log_by_game_and_player_id(db, game_id, player_id)
        if game_log:
            return game_log
        else:
            raise HTTPException(status_code=404, detail=f"Game log for goalie {player_id} and game {game_id} not found in DB")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving game log for goalie {player_id} and game {game_id} from DB: {e}")

@router.get("/skater/{player_id}/basic_stats/{season}", status_code=200, response_model=SkaterSeasonBasicStatsGetOut)
async def get_skater_season_basic_stats(player_id: int, season: int, db = Depends(get_db)):
    """Fetches basic season stats for a skater by player ID and season."""
    try:
        stats = await get_skater_season_basic_stats_from_db(db, player_id, season)
        print(stats)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving season {season} stats for skater {player_id} from DB: {e}")
    if stats is not None:
        return SkaterSeasonBasicStatsGetOut(games=stats["games"], goals=stats["goals"], assists=stats["assists"], points=stats["points"])
    else:
        return SkaterSeasonBasicStatsGetOut(games=0, goals=0, assists=0, points=0)
        #raise HTTPException(status_code=404, detail=f"Season {season} stats for skater {player_id} not found in DB")

@router.get("/skater/{player_id}/last_5/basic_stats", status_code=200, response_model=list[SkaterLast5BasicStatsGetOut])
async def get_skater_last_5_basic_stats(player_id: int, db = Depends(get_db)):
    """Fetches basic stats for a skater's last 5 games by player ID."""
    try:
        stats = await get_skater_last_5_basic_stats_from_db(db, player_id)
        if stats:
            return [SkaterLast5BasicStatsGetOut(
                date=datetime.datetime.strptime(str(stat["game_date"]), "%Y%m%d").strftime("%b %d") if stat["game_date"] else None,
                opposing_team_tricode=stat["opposing_team_tricode"],
                goals=stat["goals"],
                assists=stat["assists"],
                points=stat["points"],
                home_away=stat["home_away"]
            ) for stat in stats]
        else:
            raise HTTPException(status_code=404, detail=f"Last 5 games stats for skater {player_id} not found in DB")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving last 5 games stats for skater {player_id} from DB: {e}")

@router.get("/player/{player_id}/basic_data", status_code=200, response_model=PlayerBasicInfoOut)
async def get_player_data(player_id: int, db = Depends(get_db)):
    """Fetches basic info for a player by player ID."""
    player_info = await get_player_by_id(db, player_id)
    if not player_info:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found in DB")
    return PlayerBasicInfoOut(
        name = f"{player_info.first_name} {player_info.last_name}",
        number=player_info.number,
        position=player_info.position,
        team=player_info.current_team_tri_code if player_info.current_team_tri_code else "N/A",
        headshotUrl=player_info.headshot
    )

@router.get("/player/{player_id}/upcoming_game", status_code=200, response_model=PlayerNextGameGetOut)
async def get_player_upcoming_game(player_id: int, db = Depends(get_db)):
    """Fetches upcoming game info for a player by player ID."""
    player_info = await get_player_by_id(db, player_id)
    if not player_info:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found in DB")
    if player_info.current_team_tri_code is None:
        return PlayerNextGameGetOut(
            date=None,
            opposing_team_tricode=None,
            venue=None,
            time=None,
            home_away=None
        )
        #raise HTTPException(status_code=404, detail=f"Player {player_id} does not have a current team in DB")
    upcoming_game = await get_next_game_info_by_tri_code(db, player_info.current_team_tri_code)
    if not upcoming_game:
        raise HTTPException(status_code=404, detail=f"Upcoming game for player {player_id} not found in DB")
    return PlayerNextGameGetOut(
        # int to string from YYYYMMDD to Month Name Day, Year
        date = datetime.datetime.strptime(str(upcoming_game.date), "%Y%m%d").strftime("%B %d, %Y") if upcoming_game.date else None,
        opposing_team_tricode=upcoming_game.away_team_tri_code if upcoming_game.home_team_tri_code == player_info.current_team_tri_code else upcoming_game.home_team_tri_code,
        venue=upcoming_game.venue,
        time=upcoming_game.start_time,
        home_away="HOME" if upcoming_game.home_team_tri_code == player_info.current_team_tri_code else "AWAY"
    )

@router.get("/goalie/{player_id}/last_5/basic_stats", status_code=200, response_model=list[GoalieLast5BasicStatsGetOut])
async def get_goalie_last_5_basic_stats(player_id: int, db = Depends(get_db)):
    """Fetches basic stats for a goalie's last 5 games by player ID."""
    try:
        stats = await get_goalie_last_5_basic_stats_from_db(db, player_id)
        if stats:
            return [GoalieLast5BasicStatsGetOut(
                date=datetime.datetime.strptime(str(stat["date"]), "%Y%m%d").strftime("%b %d") if stat["date"] else None,
                opposing_team_tricode=stat["opposing_team_tricode"],
                saves=stat["saves"],
                goals_against=stat["goals_against"],
                save_percentage=round(stat["save_percentage"], 3) if stat["save_percentage"] is not None else None,
                home_away=stat["home_away"]
            ) for stat in stats]
        else:
            raise HTTPException(status_code=404, detail=f"Last 5 games stats for goalie {player_id} not found in DB")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving last 5 games stats for goalie {player_id} from DB: {e}")

@router.get("/goalie/{player_id}/basic_stats/{season}", status_code=200, response_model=GoalieSeasonBasicStatsGetOut)
async def get_goalie_season_basic_stats(player_id: int, season: int, db = Depends(get_db)):
    """Fetches basic season stats for a goalie by player ID and season."""
    try:
        stats = await get_goalie_season_basic_stats_from_db(db, player_id, season)
        if stats:
            return GoalieSeasonBasicStatsGetOut(
                games=stats["games"], 
                gaa=round(stats["gaa"], 3) if stats["gaa"] is not None else None, save_percentage=round(stats["save_percentage"], 3) if stats["save_percentage"] is not None else None)
        else:
            raise HTTPException(status_code=404, detail=f"Season {season} stats for goalie {player_id} not found in DB")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving season {season} stats for goalie {player_id} from DB: {e}")

@router.get("/search", status_code=200, response_model=list[PlayerSearchResultOut])
async def search_players(q: str = Query(..., min_length=1), limit: int = 3, db=Depends(get_db)):
    """Searches players by name."""
    results = await search_players_by_name(db, q, limit)
    return [PlayerSearchResultOut(
        id=player.id,
        first_name=player.first_name,
        last_name=player.last_name,
        position=player.position,
        current_team_tri_code=player.current_team_tri_code,
        headshot=player.headshot
    ) for player in results]

@router.get("/skater/{player_id}/prediction", status_code=200, response_model=PlayerPredictionOut)
async def get_skater_prediction(player_id: int, db = Depends(get_db)):
    """Fetches prediction for a skater's next game by player ID."""
    try:
        player_current_team = await get_player_current_team_tri_code(db, player_id)
        if player_current_team is None:
            return PlayerPredictionOut(goals=0.0, assists=0.0, points=0.0, prob_goal=0.0, prob_assist=0.0, prob_point=0.0)
        skater_next_game = await get_next_game_info_by_tri_code(db, player_current_team)
        if skater_next_game is None:
            raise HTTPException(status_code=404, detail=f"Next game for player {player_id} not found in DB")

        prediction = await predict_skater(db, player_id, player_current_team, skater_next_game)
        if prediction is None:
            raise HTTPException(status_code=404, detail=f"No game logs for skater {player_id} in DB")
        return PlayerPredictionOut(
            goals=round(prediction["goals"], 2),
            assists=round(prediction["assists"], 2),
            points=round(prediction["points"], 2),
            prob_goal=round(prediction["prob_goals"], 4),
            prob_assist=round(prediction["prob_assists"], 4),
            prob_point=round(prediction["prob_points"], 4),
        )
    except HTTPException:
        raise
    except (FileNotFoundError, LookupError) as e:
        raise HTTPException(status_code=503, detail=f"Predictions unavailable: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving prediction for skater {player_id}: {e}")

@router.get("/goalie/{player_id}/prediction", status_code=200, response_model=GoaliePredictionOut)
async def get_goalie_prediction(player_id: int, db = Depends(get_db)):
    """Fetches prediction for a goalie's next game (assuming they start) by player ID."""
    try:
        player_current_team = await get_player_current_team_tri_code(db, player_id)
        if player_current_team is None:
            return GoaliePredictionOut(goals_against=0.0, saves=0.0, save_percentage=None)
        goalie_next_game = await get_next_game_info_by_tri_code(db, player_current_team)
        if goalie_next_game is None:
            raise HTTPException(status_code=404, detail=f"Next game for goalie {player_id} not found in DB")

        prediction = await predict_goalie(db, player_id, player_current_team, goalie_next_game)
        if prediction is None:
            raise HTTPException(status_code=404, detail=f"No game logs for goalie {player_id} in DB")
        pred_ga, pred_sog = prediction["goals_against"], prediction["sog"]
        pred_saves = max(0.0, pred_sog - pred_ga)
        pred_sv_pct = (pred_saves / pred_sog) if pred_sog > 0 else None
        return GoaliePredictionOut(
            goals_against=round(pred_ga, 2),
            saves=round(pred_saves, 2),
            save_percentage=round(pred_sv_pct, 4) if pred_sv_pct is not None else None,
        )
    except HTTPException:
        raise
    except (FileNotFoundError, LookupError) as e:
        raise HTTPException(status_code=503, detail=f"Predictions unavailable: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving prediction for goalie {player_id}: {e}")

@router.get("/top_players/{player_type}/{season}/{n}", status_code=200, response_model=list[TeamRosteredPlayer])
async def get_top_players(player_type: str, season: int, n: int, db = Depends(get_db)):
    """Fetches the top n skaters or goalies from the database."""
    try:
        if player_type == "skaters":
            top_n_players = await get_top_n_skaters(db, n, season)
        elif player_type == "goalies":
            top_n_players = await get_top_n_goalies(db, n, season)
        else:
            raise HTTPException(status_code=400, detail=f"Invalid player type: {player_type}")
        if top_n_players:
            return [TeamRosteredPlayer(
                    id=player.id, 
                    headshot=player.headshot,
                    first_name=player.first_name, 
                    current_team_tri_code=player.current_team_tri_code, 
                    position=player.position if player.position else "U", 
                    last_name=player.last_name, 
                    number=player.number, 
                    shoots_catches=player.shoots_catches if player.shoots_catches else "U"
                ) for player in top_n_players]
        else:
            return []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving top {n} skaters from DB: {e}")

@router.get("/props/{player_id}", status_code=200, response_model=list[PlayerPropOut])
async def get_player_props(player_id: int, db = Depends(get_db)):
    """Fetches player props for a player from the database."""
    try:
        player_props = await get_player_props_from_db(db, player_id)
        return player_props
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving player props from DB: {e}")