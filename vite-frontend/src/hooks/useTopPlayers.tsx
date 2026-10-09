import { useState, useEffect } from "react";
import type { PlayerFullData } from "../types/player";
import { getTopPlayers } from "../api/player";

export function useTopPlayers(season: string, n: number, player_type: "skaters" | "goalies") {
    const [data, setData] = useState<PlayerFullData[] | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<Error | null>(null);

    useEffect(() => {
        getTopPlayers(season, n, player_type)
            .then(setData)
            .catch(setError)
            .finally(() => setLoading(false));
    }, [season, n, player_type]);
    return { data, loading, error };
}