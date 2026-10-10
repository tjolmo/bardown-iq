import { apiGet } from "./client";
import type { SkaterGame, SkaterGamePredictions } from "../types/skater";

export const getSkaterSeasonGames = (id: number, season: string = "current") =>
    apiGet<SkaterGame[]>(`/players/skater/${id}/game_log/${season}`);

export const getSkaterLastGames = (id: number, n: number) =>
    apiGet<SkaterGame[]>(`/players/skater/${id}/game_log/last/${n}`);

export const getSkaterPredictions = (id: number) =>
    apiGet<SkaterGamePredictions>(`/players/skater/${id}/prediction`);
