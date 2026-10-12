import { useState, useEffect } from "react";
import type { GoalieSort, PositionFilter, SkaterSort, TopGoaliesBoard, TopSkatersBoard } from "../types/player";
import type { TeamLookup } from "../types/teams";
import { getTopGoalies, getTopSkaters } from "../api/player";
import { getTeams } from "../api/teams";

interface TopPlayersState<T> {
  data: T | null;
  teams: TeamLookup;
  loading: boolean;
  error: Error | null;
}

// the teams list only names and logos the rows; without it the page still shows, on tricodes
let teamsOnce: Promise<TeamLookup> | null = null;
const loadTeams = (): Promise<TeamLookup> =>
  (teamsOnce ??= getTeams()
    .then((teams) => Object.fromEntries(teams.map((t) => [t.tricode, t])))
    .catch(() => ({})));

function useBoard<T>(load: () => Promise<T>, deps: unknown[]): TopPlayersState<T> {
  const [data, setData] = useState<T | null>(null);
  const [teams, setTeams] = useState<TeamLookup>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([load(), loadTeams()])
      .then(([board, lookup]) => {
        if (cancelled) return;
        setData(board);
        setTeams(lookup);
      })
      .catch((e) => {
        if (!cancelled) setError(e);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, teams, loading, error };
}

/** The top skaters board: the n best on `sort`, forwards or defence only when asked. */
export const useTopSkaters = (season: string, n: number, sort: SkaterSort, position: PositionFilter) =>
  useBoard<TopSkatersBoard>(() => getTopSkaters(season, n, sort, position), [season, n, sort, position]);

/** The top goalies board: the n best on `sort` among those with at least minGames games. */
export const useTopGoalies = (season: string, n: number, sort: GoalieSort, minGames: number) =>
  useBoard<TopGoaliesBoard>(() => getTopGoalies(season, n, sort, minGames), [season, n, sort, minGames]);
