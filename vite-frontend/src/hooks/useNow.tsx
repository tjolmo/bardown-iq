import { useEffect, useState } from "react";

/** The current time (ms), ticking every intervalMs while intervalMs is set. */
export function useNow(intervalMs: number | null) {
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        if (!intervalMs) return;
        const id = setInterval(() => setNow(Date.now()), intervalMs);
        return () => clearInterval(id);
    }, [intervalMs]);
    return now;
}
