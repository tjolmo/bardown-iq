import { useState, useEffect } from "react";
import { getStandings } from "../api/teams";
import type { TeamStandings } from "../types/teams";

/** Every team with its standing and next game, for the teams page. */
export const useStandings = () => {
  const [data, setData] = useState<TeamStandings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let cancelled = false;
    getStandings()
      .then((standings) => {
        if (!cancelled) setData(standings);
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
  }, []);

  return { data, loading, error };
};
