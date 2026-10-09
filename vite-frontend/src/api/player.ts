import { apiGet } from "./client";
import type { PlayerData, UpcomingGame, SearchPlayerResult, PlayerFullData, PlayerPropData } from "../types/player";

export const getPlayerBasicInfo = (id: number) =>
    apiGet<PlayerData>(`/players/player/${id}/basic_data`);

export const getPlayerUpcomingGame = (id: number) =>
    apiGet<UpcomingGame>(`/players/player/${id}/upcoming_game`);

export const getSearchPlayer = (query: string, limit: number = 10) =>
    apiGet<SearchPlayerResult[]>(`/players/search?q=${encodeURIComponent(query)}&limit=${limit}`);

export const getTopPlayers = (season: string, n: number, player_type: "skaters" | "goalies") =>
    apiGet<PlayerFullData[]>(`/players/top_players/${player_type}/${season}/${n}`);

export const getPlayerProps = (player_id: number) =>
    apiGet<PlayerPropData[]>(`/players/props/${player_id}`);
