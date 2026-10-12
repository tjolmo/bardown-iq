import { apiGet } from "./client";
import type {
    PlayerData, UpcomingGame, SearchPlayerResult, PlayerPropData, TopSkatersBoard, TopGoaliesBoard, SkaterSort, GoalieSort,
    PositionFilter,
} from "../types/player";

export const getPlayerBasicInfo = (id: number) =>
    apiGet<PlayerData>(`/players/player/${id}/basic_data`);

export const getPlayerUpcomingGame = (id: number) =>
    apiGet<UpcomingGame>(`/players/player/${id}/upcoming_game`);

export const getSearchPlayer = (query: string, limit: number = 10) =>
    apiGet<SearchPlayerResult[]>(`/players/search?q=${encodeURIComponent(query)}&limit=${limit}`);

export const getTopSkaters = (season: string, n: number, sort: SkaterSort, position: PositionFilter) =>
    apiGet<TopSkatersBoard>(`/players/top_players/skaters/${season}/${n}?sort=${sort}&position=${position}`);

export const getTopGoalies = (season: string, n: number, sort: GoalieSort, minGames: number) =>
    apiGet<TopGoaliesBoard>(`/players/top_players/goalies/${season}/${n}?sort=${sort}&min_games=${minGames}`);

export const getPlayerProps = (player_id: number) =>
    apiGet<PlayerPropData[]>(`/players/props/${player_id}`);
