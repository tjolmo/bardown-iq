import { useState, useEffect } from "react";
import type { EdgeBoard } from "../types/edges";
import type { TeamLookup } from "../types/teams";
import { getEdgeBoard } from "../api/edges";
import { getTeamLookup } from "../api/teams";

export function useEdgeBoard() {
    const [data, setData] = useState<EdgeBoard | null>(null);
    const [teams, setTeams] = useState<TeamLookup>({});
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<Error | null>(null);

    useEffect(() => {
        Promise.all([getEdgeBoard(), getTeamLookup()])
            .then(([board, lookup]) => {
                setData(board);
                setTeams(lookup);
            })
            .catch(setError)
            .finally(() => setLoading(false));
    }, []);
    return { data, teams, loading, error };
}
