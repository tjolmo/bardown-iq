import { useEffect, useState } from "react";
import { getPlayerBasicInfo, getPlayerProps, getPlayerUpcomingGame } from "../api/player";
import { getTeams } from "../api/teams";
import type { PlayerData, PlayerPropData, UpcomingGame } from "../types/player";
import type { TeamLookup } from "../types/teams";

interface Loaded<T> {
  id: number;
  data: T | null;
  error: Error | null;
}

/** What every player page needs besides its role's own numbers. Only the player's basic info is required: the rest
 *  falls back to empty when its endpoint fails, so the page still shows what it has. */
export interface PlayerBasics extends PlayerData {
  upcomingGame: UpcomingGame | null;
  props: PlayerPropData[];
  teams: TeamLookup;
}

export const loadPlayerBasics = async (id: number): Promise<PlayerBasics> => {
  const [info, upcomingGame, props, teams] = await Promise.all([
    getPlayerBasicInfo(id),
    getPlayerUpcomingGame(id).catch(() => null),
    getPlayerProps(id).catch(() => []),
    getTeams().catch(() => []),
  ]);
  return {
    ...info,
    upcomingGame: upcomingGame?.opposing_team_tricode ? upcomingGame : null,
    props,
    teams: Object.fromEntries(teams.map((t) => [t.tricode, t])),
  };
};

/** Loads a player page's data once per player id; switching tabs never refetches. */
export function usePlayerPage<T>(id: number, load: (id: number) => Promise<T>) {
  const [state, setState] = useState<Loaded<T> | null>(null);

  useEffect(() => {
    let live = true;
    load(id)
      .then((data) => live && setState({ id, data, error: null }))
      .catch((error: Error) => live && setState({ id, data: null, error }));
    return () => {
      live = false;
    };
  }, [id, load]);

  const current = state?.id === id ? state : null;
  return { data: current?.data ?? null, loading: current === null, error: current?.error ?? null };
}
