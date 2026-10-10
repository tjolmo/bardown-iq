import type { Team, TeamLookup } from "../types/teams";

/** One stat the model predicts, read off a game of type G. */
export interface StatDef<G> {
  key: string;            // the model's name for it: the key in predictions and in a game's `expected`
  label: string;          // "Shots on goal"
  short: string;          // "SOG", for table headers
  one: string;            // "shot"
  many: string;           // "shots"
  value: (g: G) => number | null;
  propTypes: string[];    // the prop markets it settles
  lowerIsBetter?: boolean;
}

export interface PlayerGame {
  date: string;
  opposing_team_tricode: string;
  home_away: "HOME" | "AWAY" | null;
  toi: number;
  expected: Record<string, number>;
}

/** The total of a stat over the games that have it (null when none do). */
export const total = <G>(games: G[], value: (g: G) => number | null): number | null => {
  const vals = games.map(value).filter((v): v is number => v !== null);
  return vals.length ? vals.reduce((a, b) => a + b, 0) : null;
};

export const perGame = <G>(games: G[], value: (g: G) => number | null): number | null => {
  const vals = games.map(value).filter((v): v is number => v !== null);
  return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
};

const MINUS = "−";

/** "+0.12", "−1.9", "0.0" */
export const signed = (x: number, digits: number): string => {
  const s = Math.abs(x).toFixed(digits);
  if (Number(s) === 0) return s;
  return (x > 0 ? "+" : MINUS) + s;
};

/** American odds with a true minus sign: "+165", "−190". */
export const americanOdds = (odds: number): string => (odds > 0 ? `+${odds}` : `${MINUS}${Math.abs(odds)}`);

/** The chance a price implies, vig included. */
export const impliedProb = (odds: number): number => (odds > 0 ? 100 / (odds + 100) : -odds / (-odds + 100));

export const pct = (p: number): string => `${Math.round(p * 100)}%`;

/** ".917" */
export const savePct = (saves: number, shots: number): string =>
  shots > 0 ? (saves / shots).toFixed(3).replace(/^0/, "") : "—";

/** 1254 -> "20:54" */
export const clock = (seconds: number): string => {
  const s = Math.round(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

/** "2026-10-08" -> "Oct 8" (the game's own calendar day, not shifted by the visitor's zone) */
export const gameDay = (iso: string): string => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", { month: "short", day: "numeric" });
};

/** The chance of at least one when the count is Poisson with this mean (what the backend's prob_* are). */
export const atLeastOne = (mean: number): number => 1 - Math.exp(-mean);

export const where = (g: { home_away: "HOME" | "AWAY" | null }): string => (g.home_away === "AWAY" ? "@" : "vs");

/** The team, or a stand-in built from its tricode when the teams list didn't load. */
export const teamOf = (teams: TeamLookup, tricode: string): Team =>
  teams[tricode] ?? { tricode, name: tricode, logoUrl: `https://assets.nhle.com/logos/nhl/svg/${tricode}_light.svg` };

export const POSITION_NAMES: Record<string, string> = {
  C: "Centre", L: "Left wing", R: "Right wing", D: "Defence", G: "Goaltender",
};

/** Goals against per 60 minutes of ice time. */
export const gaa = (games: { goals_against: number; toi: number }[]): number | null => {
  const seconds = games.reduce((s, g) => s + g.toi, 0);
  return seconds > 0 ? games.reduce((s, g) => s + g.goals_against, 0) / (seconds / 3600) : null;
};
