import { useState, useEffect } from "react";
import type { EdgeBoard } from "../types/edges";
import { getEdgeBoard } from "../api/edges";

export function useEdgeBoard() {
    const [data, setData] = useState<EdgeBoard | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<Error | null>(null);

    useEffect(() => {
        getEdgeBoard()
            .then(setData)
            .catch(setError)
            .finally(() => setLoading(false));
    }, []);
    return { data, loading, error };
}
