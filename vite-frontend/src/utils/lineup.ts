import type { LineupPlayer, TeamInjury, TeamLineup } from "../types/lineup";

/** Seconds as "6:42". */
export const formatSeconds = (seconds: number): string =>
  `${Math.floor(seconds / 60)}:${String(Math.round(seconds) % 60).padStart(2, "0")}`;

// ESPN's statuses as the page says them; out / suspended keep a player out, IR and LTIR are long stays
export const INJURY_LABEL: Record<string, string> = {
  out: "OUT", ir: "IR", ltir: "LTIR", suspended: "SUSPENDED", day_to_day: "DAY-TO-DAY",
};

/** The chip class of an injury status: ink for out tonight, outlined for injured reserve, quiet for day-to-day. */
export const injuryChipClass = (status: string): string =>
  status === "day_to_day" ? "bd-chip-quiet" : status === "ir" || status === "ltir" ? "bd-chip-time" : "bd-chip-final";

export const injuryLabel = (status: string): string => INJURY_LABEL[status] ?? status.replace(/_/g, " ").toUpperCase();

/** ESPN's short comment when it says something ("out" and "ir-nr" only repeat the status). */
export const usefulComment = (comment: string | null): string | null =>
  comment && comment.trim().length > 20 ? comment.trim() : null;

/** "Est. return Oct 13" from ESPN's estimate (a date, no time zone). */
export const returnLabel = (date: string | null): string | null => {
  if (!date) return null;
  const d = new Date(`${date}T12:00:00`);
  return Number.isNaN(d.getTime()) ? null : `Est. return ${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;
};

export const playerLink = (p: Pick<LineupPlayer, "id" | "position" | "slot">): string =>
  p.position === "G" || p.slot === "G" ? `/goalie/${p.id}` : `/player/${p.id}`;

export const lastName = (p: LineupPlayer): string => p.lastName ?? `#${p.number ?? "?"}`;

/** "6:42 last game · 3 of 5 games" (the games: those it played a minute or more together), or null for a group
 *  that hasn't played together. */
export const togetherLine = (secondsLastGame: number, gamesTogether: number, games: number): string | null => {
  if (secondsLastGame <= 0 && gamesTogether <= 0) return null;
  const last = secondsLastGame > 0 ? `${formatSeconds(secondsLastGame)} last game` : "Not together last game";
  return gamesTogether > 0 ? `${last} · ${gamesTogether} of ${games} games` : last;
};

export interface TonightRole {
  label: string;
  // chip class: quiet (in the lineup), final (coming in, or out tonight), time (injured reserve)
  chip: string;
}

/** Each player's place tonight, for the roster table: line and slot, goalie role, scratch or injury. */
export const tonightRoles = (lineup: TeamLineup): Map<number, TonightRole> => {
  const roles = new Map<number, TonightRole>();
  const incoming = new Set(lineup.changes.playersIn.map((p) => p.id));
  const tag = (p: LineupPlayer, label: string) => {
    const extra = [incoming.has(p.id) ? "IN" : null, p.injuryStatus === "day_to_day" ? "DTD" : null].filter(Boolean);
    roles.set(p.id, { label: [label, ...extra].join(" · "), chip: incoming.has(p.id) ? "bd-chip-final" : "bd-chip-quiet" });
  };
  lineup.forwards.forEach((u, i) => u.players.forEach((p) => tag(p, `LINE ${i + 1} · ${p.slot ?? "F"}`)));
  lineup.defense.forEach((u, i) => u.players.forEach((p) => tag(p, `PAIR ${i + 1} · ${p.slot ?? "D"}`)));
  lineup.extras.forEach((p) => tag(p, "EXTRA"));
  lineup.goalies.forEach((g) => tag(g.player, g.role === "starter" ? "STARTER" : "BACKUP"));
  lineup.scratches.forEach((s) => {
    if (!roles.has(s.player.id)) {
      roles.set(s.player.id, { label: s.healthy ? "HEALTHY SCRATCH" : "SCRATCHED", chip: "bd-chip-quiet" });
    }
  });
  lineup.injuries.forEach((i: TeamInjury) => {
    if (i.playerId !== null && !roles.has(i.playerId)) {
      const what = i.injuryType ? ` · ${i.injuryType.toUpperCase()}` : "";
      roles.set(i.playerId, { label: `${injuryLabel(i.status)}${what}`, chip: injuryChipClass(i.status) });
    }
  });
  return roles;
};

/** The coach's note on the changes: a winger moved to centre, the most visible shuffle. */
export const lineupNote = (lineup: TeamLineup): string | null => {
  for (const unit of lineup.forwards) {
    const moved = unit.players.find((p) => p.slot === "C" && p.position && p.position !== "C");
    if (moved?.lastName) return `${moved.lastName.toLowerCase()} slides to centre`;
  }
  return null;
};
