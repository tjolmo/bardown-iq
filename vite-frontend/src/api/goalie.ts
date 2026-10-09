import { apiGet } from "./client";
import type { GoalieGameStats, GoalieSeasonStats, GoalieGamePredictions } from "../types/goalie";

export const getGoalieSeasonStats = (id: number) =>
    apiGet<GoalieSeasonStats>(`/players/goalie/${id}/basic_stats/current`);

export const getGoalieRecentGames = (id: number) =>
    apiGet<GoalieGameStats[]>(`/players/goalie/${id}/last_5/basic_stats`);

export const getGoaliePredictions = (id: number) =>
    apiGet<GoalieGamePredictions>(`/players/goalie/${id}/prediction`);