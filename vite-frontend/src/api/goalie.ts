import { apiGet } from "./client";
import type { GoalieGame, GoalieGamePredictions } from "../types/goalie";

export const getGoalieSeasonGames = (id: number, season: string = "current") =>
    apiGet<GoalieGame[]>(`/players/goalie/${id}/game_log/${season}`);

export const getGoalieLastGames = (id: number, n: number) =>
    apiGet<GoalieGame[]>(`/players/goalie/${id}/game_log/last/${n}`);

export const getGoaliePredictions = (id: number) =>
    apiGet<GoalieGamePredictions>(`/players/goalie/${id}/prediction`);
