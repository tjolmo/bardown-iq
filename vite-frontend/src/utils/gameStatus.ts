import type { TeamGameLive, TeamScheduledGame } from "../types/teams";

export type GamePhase = "pre" | "live" | "final";

// NHL game states: FUT / PRE before puck drop, LIVE / CRIT under way, FINAL / OFF over
const LIVE_STATES = new Set(["LIVE", "CRIT"]);
const FINAL_STATES = new Set(["FINAL", "OFF"]);

export const gamePhase = (game: TeamScheduledGame): GamePhase => {
  if (game.gameState && LIVE_STATES.has(game.gameState)) return "live";
  if (game.gameState && FINAL_STATES.has(game.gameState)) return "final";
  return "pre";
};

const ORDINALS = ["1ST", "2ND", "3RD"];

/** "2ND", "OT", "2OT", "SO" for a period number and type. */
export const periodLabel = (period: number | null, periodType: string | null): string => {
  if (periodType === "SO") return "SO";
  if (periodType === "OT" || (period !== null && period > 3)) {
    const n = period !== null ? period - 3 : 1;
    return n > 1 ? `${n}OT` : "OT";
  }
  return period !== null && period >= 1 && period <= 3 ? ORDINALS[period - 1] : "";
};

export const formatClock = (seconds: number): string => {
  const s = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
};

/** The intermission time left now, counting down from when the server answered. */
export const intermissionLeft = (live: TeamGameLive, receivedAt: number, now: number): number | null =>
  live.secondsRemaining === null ? null : Math.max(0, live.secondsRemaining - (now - receivedAt) / 1000);

export interface StatusChipInfo {
  kind: "time" | "live" | "final";
  text: string;
  title?: string;
}

// times in the visitor's own time zone, named so it's clear: "7:00 PM PT" ("PDT" where the generic name isn't supported)
const localTimeFormat = (): Intl.DateTimeFormat => {
  try {
    return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", timeZoneName: "shortGeneric" });
  } catch {
    return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", timeZoneName: "short" });
  }
};
const LOCAL_TIME = localTimeFormat();

export const localTime = (iso: string): string => LOCAL_TIME.format(new Date(iso));

/** What the card's status chip says: puck drop, the period and clock (or intermission time left), or FINAL. */
export const statusChip = (game: TeamScheduledGame, receivedAt: number, now: number): StatusChipInfo => {
  const phase = gamePhase(game);
  const live = game.live ?? null;
  if (phase === "pre") return { kind: "time", text: localTime(game.time) };
  if (phase === "final") {
    const how = live?.periodType === "OT" || live?.periodType === "SO" ? `/${periodLabel(live.period, live.periodType)}` : "";
    return { kind: "final", text: `FINAL${how}` };
  }
  if (!live) return { kind: "live", text: "LIVE" };
  const period = periodLabel(live.period, live.periodType);
  const asOf = `Clock as of ${localTime(live.asOf)}`;
  if (live.inIntermission) {
    const left = intermissionLeft(live, receivedAt, now);
    const name = period ? `${period} INT` : "INTERMISSION";
    return { kind: "live", text: left !== null && left > 0 ? `${name} · ${formatClock(left)} LEFT` : name };
  }
  if (live.periodType === "SO") return { kind: "live", text: "LIVE · SHOOTOUT" };
  if (live.secondsRemaining === 0) return { kind: "live", text: period ? `END OF ${period}` : "LIVE", title: asOf };
  const clock = live.timeRemaining ? ` ${live.timeRemaining}` : "";
  return { kind: "live", text: `LIVE · ${period}${clock}`.trim(), title: asOf };
};

/** American odds with a true minus sign: "−120", "+190". */
export const formatAmerican = (odds: number): string => {
  const rounded = Math.round(odds);
  return rounded > 0 ? `+${rounded}` : `−${Math.abs(rounded)}`;
};

/** Edge in signed points to one decimal: "+7.2". */
export const formatEdge = (points: number): string =>
  `${points >= 0 ? "+" : "−"}${Math.abs(points).toFixed(1)}`;

// nicknames of more than one word; every other team's nickname is its last word
const TWO_WORD_NICKNAMES = ["Maple Leafs", "Red Wings", "Blue Jackets", "Golden Knights"];

/** "Toronto Maple Leafs" -> { city: "Toronto", nickname: "Maple Leafs" }. */
export const splitTeamName = (name: string): { city: string; nickname: string } => {
  const nickname = TWO_WORD_NICKNAMES.find((n) => name.endsWith(` ${n}`)) ?? name.split(" ").slice(-1)[0];
  return { city: name.slice(0, name.length - nickname.length).trim(), nickname };
};
