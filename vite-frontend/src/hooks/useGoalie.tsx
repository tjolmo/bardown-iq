import { getGoalieLastGames, getGoaliePredictions, getGoalieSeasonGames } from "../api/goalie";
import type { GoalieData } from "../types/goalie";
import { loadPlayerBasics, usePlayerPage } from "./usePlayerPage";

const loadGoalie = async (id: number): Promise<GoalieData> => {
  const [basics, predictions, season, recent] = await Promise.all([
    loadPlayerBasics(id),
    getGoaliePredictions(id).catch(() => null),
    getGoalieSeasonGames(id).catch(() => []),
    getGoalieLastGames(id, 5).catch(() => []),
  ]);
  return { ...basics, predictions, season, recent };
};

export const useGoalie = (id: number) => usePlayerPage(id, loadGoalie);
