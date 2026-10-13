import { useCallback, useState } from "react";

const read = <T,>(key: string, fallback: T, valid: (v: unknown) => v is T): T => {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    const v: unknown = JSON.parse(raw);
    return valid(v) ? v : fallback;
  } catch {
    return fallback;
  }
};

/** State kept in this browser between visits (a preference, not data): falls back to `fallback` when storage is
 *  empty, blocked, or holds something `valid` rejects. */
export function useStoredState<T>(key: string, fallback: T, valid: (v: unknown) => v is T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => read(key, fallback, valid));
  const set = useCallback((v: T) => {
    setValue(v);
    try {
      localStorage.setItem(key, JSON.stringify(v));
    } catch {
      // storage blocked: the choice lasts this visit only
    }
  }, [key]);
  return [value, set];
}
