from external.nhl.games import get_odds_for_current_games, get_live_statuses
from app.game_board import needs_live_status, live_out, game_edge, has_started
from app.crud.prediction_log import get_pregame_home_win_probs
from app.crud.game_line_quotes import get_moneylines
from app.crud.odds_snapshots import closing_game_snapshots
from predictions.predict import get_upcoming_game_prediction
from app.crud.teams import search_teams_by_name
from app.schedules import current_game_day
from fastapi import Query
from app.schemas.teams import TeamSearchResultOut, TeamLineupOut
from app.team_lineup import build_team_lineup
import datetime
from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import get_db
from app.crud.teams import get_team_by_tri_code, check_tri_code_exists, get_team_current_roster, get_all_teams
from app.crud.games import get_all_games_for_date, get_next_n_games_info_by_tri_code, get_team_last_5_games
from app.schemas.teams import TeamBasicInfoOut, Last5GameInfoOut, TeamScheduledGameInfoOut, TeamRosteredPlayer, TeamSidePrediction, TeamGamePredictionOut, TeamMoneylineOut

router = APIRouter(prefix="/teams", tags=["teams"])


async def moneylines_for(db, games, nhl_fallback: bool, live_statuses: dict | None = None) -> dict[int, TeamMoneylineOut]:
    """game_id -> moneyline. Started and finished games: ESPN's close (closing_game_snapshots, never an in-game
    price), else PropLine's last quote. Upcoming games: PropLine's books (game_line_quotes), else NHL's partner feed
    for today's games."""
    live_statuses = live_statuses or {}
    game_ids = [g.id for g in games]
    started = {g.id for g in games if has_started(g, live_statuses.get(g.id))}
    out = {}
    for gid, snap in (await closing_game_snapshots(db, [gid for gid in game_ids if gid in started])).items():
        if snap.home_moneyline is not None and snap.away_moneyline is not None:
            out[gid] = TeamMoneylineOut(home=round(snap.home_moneyline), away=round(snap.away_moneyline), source="espn")
    for gid, m in (await get_moneylines(db, [gid for gid in game_ids if gid not in out])).items():
        out[gid] = TeamMoneylineOut(**m)
    upcoming = {gid for gid in game_ids if gid not in started}
    if nhl_fallback and upcoming - out.keys():
        for odd in await get_odds_for_current_games() or []:
            if odd.game_id in upcoming and odd.game_id not in out:
                out[odd.game_id] = TeamMoneylineOut(home=odd.home_moneyline, away=odd.away_moneyline, source="nhl")
    return out


@router.get("/last5/{tri_code}", status_code=200, response_model=list[Last5GameInfoOut])
async def get_last_5_games(tri_code: str, db = Depends(get_db)):
    if not await check_tri_code_exists(db, tri_code):
        raise HTTPException(status_code=404, detail=f"Team {tri_code} not found in DB")
    last_5 = await get_team_last_5_games(db, tri_code)
    if last_5 is not None:
        return [Last5GameInfoOut(game_id=game.id, date=game.date, home_team_tri_code=game.home_team_tri_code, away_team_tri_code=game.away_team_tri_code, home_score=game.home_score, away_score=game.away_score) for game in last_5]
    raise HTTPException(status_code=404, detail=f"No games found for Team {tri_code} in DB")

@router.get("/{tri_code}/basic_info", status_code=200, response_model=TeamBasicInfoOut)
async def get_team_basic_info(tri_code: str, db = Depends(get_db)):
    team = await get_team_by_tri_code(db, tri_code)
    if team is not None:
        return TeamBasicInfoOut(
            name=team.current_name,
            tricode=team.tri_code,
            logoUrl=f"https://assets.nhle.com/logos/nhl/svg/{team.tri_code}_light.svg" if team.tri_code else None
        )
    raise HTTPException(status_code=404, detail=f"Team {tri_code} not found in DB")

@router.get("/{tri_code}/next_5/{offset}", status_code=200, response_model=list[TeamScheduledGameInfoOut])
async def get_team_next_5_games(tri_code: str, offset: int, db = Depends(get_db)):
    next_5_games = await get_next_n_games_info_by_tri_code(db, tri_code, 5, offset)
    next_5_cleaned = []
    if next_5_games is not None:
        moneyline_odds = await moneylines_for(db, next_5_games, nhl_fallback=True)
        for i, game in enumerate(next_5_games):
            try: 
                home_team = await get_team_by_tri_code(db, game.home_team_tri_code)
                away_team = await get_team_by_tri_code(db, game.away_team_tri_code)
                homeTeam = TeamBasicInfoOut(name=home_team.current_name, 
                                            tricode=home_team.tri_code, 
                                            logoUrl=f"https://assets.nhle.com/logos/nhl/svg/{home_team.tri_code}_light.svg" if home_team.tri_code else None
                        )
                awayTeam = TeamBasicInfoOut(name=away_team.current_name, 
                                            tricode=away_team.tri_code, 
                                            logoUrl=f"https://assets.nhle.com/logos/nhl/svg/{away_team.tri_code}_light.svg" if away_team.tri_code else None
                        )
            except Exception as e:
                return HTTPException(status_code=500, detail=f"Error fetching team info for game {game.id}: {e}")

            prediction = await get_upcoming_game_prediction(game, db)
            prob_home_win, prob_away_win = prediction if prediction is not None else (None, None)

            game_info =TeamScheduledGameInfoOut(
                id=game.id,
                date=datetime.datetime.strptime(str(game.date), "%Y%m%d").strftime("%B %d, %Y") if game.date else None,
                homeTeam=homeTeam,
                awayTeam=awayTeam,
                time=game.start_time,
                venue=game.venue,
                awayScore=game.away_score,
                gameState=game.game_state,
                homeScore=game.home_score,
                predictions=TeamGamePredictionOut(
                    home=TeamSidePrediction(tri_code=game.home_team_tri_code, prob_win=prob_home_win),
                    away=TeamSidePrediction(tri_code=game.away_team_tri_code, prob_win=prob_away_win),
                ),
                moneyline=moneyline_odds.get(game.id),
                isNextGame=True if i == 0 and offset == 0 else False,
                edge=game_edge(game.home_team_tri_code, game.away_team_tri_code, prob_home_win, prob_away_win,
                               moneyline_odds.get(game.id)),
            )
            next_5_cleaned.append(game_info)
        return next_5_cleaned
    raise HTTPException(status_code=404, detail=f"No future games found for Team {tri_code} in DB")

@router.get("/games/{date}", status_code=200, response_model=list[TeamScheduledGameInfoOut])
async def get_all_games_from_date(db = Depends(get_db), date: str="today"):
    # the NHL game day, not the container's UTC date: at midnight UTC (5pm PT) tonight's games are still "today"
    today_int_date = int(current_game_day().strftime("%Y%m%d"))

    if date == "today":
        int_date = today_int_date
    else:
        try:
            int_date = int(date)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid date format. Please use YYYYMMDD or 'today'")
    
    games = await get_all_games_for_date(db, int_date)
    cleaned_games = []

    if games is None or len(games) == 0:
        return []
    # period, clock and intermission of today's games under way, and their score fresher than the stored one
    live_statuses = await get_live_statuses() if int_date == today_int_date and needs_live_status(games) else {}
    # ESPN's close for games under way or over; PropLine's lines for any date it priced; NHL's partner feed (today only)
    moneyline_odds = await moneylines_for(db, games, nhl_fallback=int_date == today_int_date, live_statuses=live_statuses)
    # the model's frozen pre-game call for games under way or over (the live prediction covers unstarted games only)
    logged_home_probs = await get_pregame_home_win_probs(db, [g.id for g in games])
    for i, game in enumerate(games):
        try: 
            home_team = await get_team_by_tri_code(db, game.home_team_tri_code)
            away_team = await get_team_by_tri_code(db, game.away_team_tri_code)
            homeTeam = TeamBasicInfoOut(name=home_team.current_name, 
                                            tricode=home_team.tri_code, 
                                            logoUrl=f"https://assets.nhle.com/logos/nhl/svg/{home_team.tri_code}_light.svg" if home_team.tri_code else None
                        )
            awayTeam = TeamBasicInfoOut(name=away_team.current_name, 
                                            tricode=away_team.tri_code, 
                                            logoUrl=f"https://assets.nhle.com/logos/nhl/svg/{away_team.tri_code}_light.svg" if away_team.tri_code else None
                        )
        except Exception as e:
            return HTTPException(status_code=500, detail=f"Error fetching team info for game {game.id}: {e}")

        status = live_statuses.get(game.id)
        prob_home_win = prob_away_win = None
        started = has_started(game, status)
        # started and finished games: what the model logged before puck drop; unstarted ones: its current call
        # (each falls back to the other: an unlogged game the cached prediction still holds, a stale log)
        if started and game.id in logged_home_probs:
            prob_home_win = logged_home_probs[game.id]
            prob_away_win = 1.0 - prob_home_win
        elif int_date >= today_int_date:
            prediction = await get_upcoming_game_prediction(game, db)
            if prediction is not None:
                prob_home_win, prob_away_win = prediction
        if prob_home_win is None and game.id in logged_home_probs:
            prob_home_win = logged_home_probs[game.id]
            prob_away_win = 1.0 - prob_home_win
        has_prediction = prob_home_win is not None
        game_info = TeamScheduledGameInfoOut(
            id=game.id,
            date=datetime.datetime.strptime(str(game.date), "%Y%m%d").strftime("%B %d, %Y") if game.date else None,
            homeTeam=homeTeam,
            awayTeam=awayTeam,
            time=game.start_time,
            venue=game.venue,
            awayScore=status.away_score if status and status.away_score is not None else game.away_score,
            homeScore=status.home_score if status and status.home_score is not None else game.home_score,
            gameState=status.game_state if status else game.game_state,
            predictions=TeamGamePredictionOut(
                home=TeamSidePrediction(tri_code=game.home_team_tri_code, prob_win=prob_home_win),
                away=TeamSidePrediction(tri_code=game.away_team_tri_code, prob_win=prob_away_win)
                ) if int_date >= today_int_date or has_prediction else None,
            moneyline=moneyline_odds.get(game.id),
            isNextGame=False,
            live=live_out(status),
            edge=game_edge(game.home_team_tri_code, game.away_team_tri_code, prob_home_win, prob_away_win,
                           moneyline_odds.get(game.id)),
        )
        cleaned_games.append(game_info)
    if len(cleaned_games) == 0:
        raise HTTPException(status_code=404, detail=f"No games found for today in DB")
    return cleaned_games

@router.get("/{tri_code}/current_roster", status_code=200, response_model=list[TeamRosteredPlayer] | None)
async def get_team_current_roster_endpoint(tri_code: str, db = Depends(get_db)):
    roster = await get_team_current_roster(db, tri_code)
    if roster is not None:
        return [TeamRosteredPlayer(
                    id=player.id, 
                    headshot=player.headshot,
                    first_name=player.first_name, 
                    current_team_tri_code=player.current_team_tri_code, 
                    position=player.position if player.position else "U", 
                    last_name=player.last_name, 
                    number=player.number, 
                    shoots_catches=player.shoots_catches if player.shoots_catches else "U"
                ) for player in roster]
    raise HTTPException(status_code=404, detail=f"Roster for Team {tri_code} not found in DB")

@router.get("/{tri_code}/lineup", status_code=200, response_model=TeamLineupOut)
async def get_team_lineup(tri_code: str, db = Depends(get_db)):
    """The next game's lines (posted by the NHL shortly before puck drop, else projected from recent shift charts),
    goalies, ESPN's injury report and the NHL's scratches for one team."""
    if not await check_tri_code_exists(db, tri_code.upper()):
        raise HTTPException(status_code=404, detail=f"Team {tri_code} not found in DB")
    return await build_team_lineup(db, tri_code)

@router.get("/all", status_code=200, response_model=list[TeamBasicInfoOut])
async def get_all_teams_basic_info(db = Depends(get_db)):
    teams = await get_all_teams(db)
    if teams is not None:
        return_list = [TeamBasicInfoOut(name=team.current_name, tricode=team.tri_code, logoUrl=f"https://assets.nhle.com/logos/nhl/svg/{team.tri_code}_light.svg" if team.tri_code else None) for team in teams]
        # temp fix, no coyotes
        return_list.remove(TeamBasicInfoOut(name="Arizona Coyotes", tricode="ARI", logoUrl="https://assets.nhle.com/logos/nhl/svg/ARI_light.svg"))
        return return_list
    raise HTTPException(status_code=404, detail=f"No teams found in DB")

@router.get("/search", status_code=200, response_model=list[TeamSearchResultOut])
async def search_teams(q: str = Query(..., min_length=1), limit: int = 3, db=Depends(get_db)):
    """Searches teams by name."""
    results = await search_teams_by_name(db, q, limit)
    return [TeamSearchResultOut(
        name=team.current_name,
        tricode=team.tri_code,
        logoUrl=f"https://assets.nhle.com/logos/nhl/svg/{team.tri_code}_light.svg" if team.tri_code else None,
    ) for team in results]