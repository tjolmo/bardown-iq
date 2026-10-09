import { apiGet } from "./client";
import { type SkaterSeasonStats, type SkaterGameStats, type SkaterGamePredictions } from "../types/skater";

export const getSkaterSeasonStats = (id: number) =>
    apiGet<SkaterSeasonStats>(`/players/skater/${id}/basic_stats/current`);

export const getSkaterRecentGames = (id: number) =>
    apiGet<SkaterGameStats[]>(`/players/skater/${id}/last_5/basic_stats`);

export const getSkaterPredictions = (id: number) =>
    apiGet<SkaterGamePredictions>(`/players/skater/${id}/prediction`);
