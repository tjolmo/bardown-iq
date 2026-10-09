import { useState, useEffect } from "react";
import type { TeamScheduledGame } from "../types/teams";
import { getGamesByDate } from "../api/games";

/** A day's games. With refreshMs, refetched quietly on that interval (live scores, clocks) for as long as
 * refreshWhile(games) holds (always, without it). receivedAt is when the shown data arrived (ms), for counting an
 * intermission down between fetches. */
export function useDateGames(
    date: string,
    refreshMs: number | null = null,
    refreshWhile?: (games: TeamScheduledGame[]) => boolean,
) {
    const [data, setData] = useState<TeamScheduledGame[] | null>(null);
    const [receivedAt, setReceivedAt] = useState(0);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<Error | null>(null);
    // the date the shown data belongs to: a new date shows loading instead of the previous day's games
    const [loadedDate, setLoadedDate] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        getGamesByDate(date)
            .then((games) => {
                if (cancelled) return;
                setData(games);
                setReceivedAt(Date.now());
                setError(null);
            })
            .catch((e) => {
                if (!cancelled) setError(e);
            })
            .finally(() => {
                if (cancelled) return;
                setLoading(false);
                setLoadedDate(date);
            });
        return () => {
            cancelled = true;
        };
    }, [date]);

    const refreshing = !!refreshMs && loadedDate === date && !!data && (!refreshWhile || refreshWhile(data));

    useEffect(() => {
        if (!refreshing || !refreshMs) return;
        let cancelled = false;
        const id = setInterval(() => {
            getGamesByDate(date)
                .then((games) => {
                    if (cancelled) return;
                    setData(games);
                    setReceivedAt(Date.now());
                })
                // a failed refresh keeps the board as it was; the next one tries again
                .catch(() => {});
        }, refreshMs);
        return () => {
            cancelled = true;
            clearInterval(id);
        };
    }, [date, refreshMs, refreshing]);

    const current = loadedDate === date;
    return {
        data: current ? data : null,
        loading: loading || !current,
        error: current ? error : null,
        receivedAt,
    };
}
