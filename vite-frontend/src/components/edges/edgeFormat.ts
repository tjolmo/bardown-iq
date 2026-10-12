import type { PricedPlayer } from "../../utils/edgePricing";

// an edge of 3% or more gets the dark chip, as on the player page's prop board
export const STRONG_EDGE = 0.03;

/** "+19.8%", "−4.1%" */
export const edgeText = (edge: number): string =>
  `${edge > 0 ? "+" : edge < 0 ? "−" : ""}${Math.abs(edge * 100).toFixed(1)}%`;

export const edgeChipClass = (edge: number | null): string =>
  edge === null || edge <= 0 ? "bd-edge ed-edge-none" : edge >= STRONG_EDGE ? "bd-edge bd-edge-strong" : "bd-edge";

export const sideName = (side: string): string => {
  const s = side.toUpperCase();
  return s === "YES" ? "Yes" : s === "UNDER" ? "Under" : "Over";
};

export const isYes = (side: string): boolean => side.toUpperCase() === "YES";

export const fullName = (p: PricedPlayer): string => `${p.first_name} ${p.last_name}`;

export const playerPath = (p: PricedPlayer): string => `/${p.position === "G" ? "goalie" : "player"}/${p.player_id}`;

export const SHORT_POSITION: Record<string, string> = { C: "C", L: "LW", R: "RW", D: "D", G: "G" };

// the short names the filter pills and by-game lines use; the rest read in full
export const SHORT_MARKETS: Record<string, string> = {
  player_shots_on_goal: "SOG", player_power_play_points: "PPP", player_blocked_shots: "Blocks", player_total_saves: "Saves",
};
