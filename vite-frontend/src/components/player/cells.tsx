import { Link } from "react-router-dom";
import { gameDay, signed, total, where, type PlayerGame, type StatDef } from "../../utils/playerStats";
import type { Cell } from "./StatTable";

// the cells every game row starts with, and the plain ones after them

export const dateCell = (g: PlayerGame): Cell => ({ v: gameDay(g.date), cls: "pl-c-date" });

export const oppCell = (g: PlayerGame): Cell => ({
  pre: where(g),
  v: <Link to={`/roster/${g.opposing_team_tricode}`}>{g.opposing_team_tricode}</Link>,
  cls: "pl-c-opp",
});

/** A count, greyed when zero; a dash when the game has no number for it. */
export const numCell = (v: number | null): Cell =>
  v === null ? { v: "—", cls: "pl-c-dim" } : { v: String(v), cls: v === 0 ? "pl-c-dim" : undefined };

export const textCell = (v: string, exp?: string): Cell => ({ v, exp });

export const blankCell: Cell = { v: "" };

/** A model-view total: the season's count, and how far it ran over or under the model in the games it logged. */
export function modelFoot<G extends { expected: Record<string, number> }>(games: G[], d: StatDef<G>): Cell {
  const logged = games.filter((g) => d.value(g) !== null && g.expected[d.key] !== undefined);
  const actual = total(logged, d.value) ?? 0;
  const expected = logged.reduce((s, g) => s + g.expected[d.key], 0);
  return { v: String(total(games, d.value) ?? "—"), exp: logged.length ? `${signed(actual - expected, 1)} vs model` : "not logged" };
}
