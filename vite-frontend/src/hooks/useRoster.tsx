import { useState, useEffect } from "react";
import type { PlayerFullData } from "../types/player";
import type { TeamLineup } from "../types/lineup";
import type { Team } from "../types/teams";
import { getTeamCurrentRoster, getTeamLineup, getTeams } from "../api/teams";

interface Loaded<T> {
  tricode: string;
  data: T | null;
  error: Error | null;
}

/** The roster page's data: the roster, the next game's lineup and every team (names and logos). Each loads on its
 *  own, so the roster still shows when the lineup can't be built (no games yet, the API down). Results are kept with
 *  the team they belong to, so switching teams shows loading instead of the previous team's data. */
export const useRoster = (tricode: string) => {
  const [roster, setRoster] = useState<Loaded<{ players: PlayerFullData[]; teams: Team[] | null }> | null>(null);
  const [lineup, setLineup] = useState<Loaded<TeamLineup> | null>(null);

  useEffect(() => {
    let current = true;
    Promise.all([getTeamCurrentRoster(tricode), getTeams().catch(() => null)])
      .then(([players, teams]) => current && setRoster({ tricode, data: { players, teams }, error: null }))
      .catch((error) => current && setRoster({ tricode, data: null, error }));
    getTeamLineup(tricode)
      .then((data) => current && setLineup({ tricode, data, error: null }))
      .catch((error) => current && setLineup({ tricode, data: null, error }));
    return () => {
      current = false;
    };
  }, [tricode]);

  const rosterNow = roster?.tricode === tricode ? roster : null;
  const lineupNow = lineup?.tricode === tricode ? lineup : null;
  return {
    roster: rosterNow?.data?.players ?? null,
    teams: rosterNow?.data?.teams ?? null,
    lineup: lineupNow?.data ?? null,
    loading: rosterNow === null,
    lineupLoading: lineupNow === null,
    error: rosterNow?.error ?? null,
    lineupError: lineupNow?.error ?? null,
  };
};
