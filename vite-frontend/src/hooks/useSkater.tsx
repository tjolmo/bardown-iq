import { getSkaterLastGames, getSkaterPredictions, getSkaterSeasonGames } from "../api/skater";
import type { SkaterData } from "../types/skater";
import { loadPlayerBasics, usePlayerPage } from "./usePlayerPage";

const loadSkater = async (id: number): Promise<SkaterData> => {
  const [basics, predictions, season, recent] = await Promise.all([
    loadPlayerBasics(id),
    getSkaterPredictions(id).catch(() => null),
    getSkaterSeasonGames(id).catch(() => []),
    getSkaterLastGames(id, 5).catch(() => []),
  ]);
  return { ...basics, predictions, season, recent };
};

export const useSkater = (id: number) => usePlayerPage(id, loadSkater);
