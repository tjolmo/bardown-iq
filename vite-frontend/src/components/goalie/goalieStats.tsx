import type { GoalieGame, GoalieGamePredictions } from "../../types/goalie";
import { clock, gaa, perGame, savePct, signed, total, type StatDef } from "../../utils/playerStats";
import { blankCell, dateCell, modelFoot, numCell, oppCell, textCell } from "../player/cells";
import type { SeasonView } from "../player/SeasonLog";
import type { Cell, TableSpec } from "../player/StatTable";

/** Every stat the goalie models predict (backend predictions/config.py GOALIE_TARGETS). */
export const GOALIE_STATS: StatDef<GoalieGame>[] = [
  { key: "saves", label: "Saves", short: "SV", one: "save", many: "saves", value: (g) => g.saves, propTypes: ["player_total_saves"] },
  { key: "sog", label: "Shots against", short: "SA", one: "shot against", many: "shots against", value: (g) => g.shots_against, propTypes: [] },
  { key: "goals_against", label: "Goals against", short: "GA", one: "goal against", many: "goals against", value: (g) => g.goals_against, propTypes: [], lowerIsBetter: true },
];

export const DEFAULT_GOALIE_STAT = "saves";

export const goalieExpected = (p: GoalieGamePredictions | null, key: string): number | null => {
  if (!p) return null;
  if (key === "saves") return p.saves;
  if (key === "goals_against") return p.goals_against;
  return p.shots_against ?? null;
};

// a start shorter than this was cut short: pulled, or relief
const PARTIAL_GAME_SECONDS = 3300;

const gsax = (games: GoalieGame[]) => games.reduce((s, g) => s + g.x_goals_against - g.goals_against, 0);
const svPctOf = (games: GoalieGame[]) => savePct(total(games, (g) => g.saves) ?? 0, total(games, (g) => g.shots_against) ?? 0);

export const goalieSeasonViews = (stat: string): SeasonView<GoalieGame>[] => {
  const statCols = GOALIE_STATS.map((d) => ({ label: d.short, hl: d.key === stat }));
  const avg = (gs: GoalieGame[], f: (g: GoalieGame) => number) => (perGame(gs, f) ?? 0).toFixed(2);
  return [
    {
      id: "box",
      label: "Box score",
      caption: "Every start, newest first. A filled TOI marks a game cut short: pulled, or in relief.",
      table: (games): TableSpec => ({
        label: "Box score by start",
        grid: "70px 88px 70px repeat(4, minmax(56px, 1fr))",
        minWidth: 560,
        cols: [{ label: "Date" }, { label: "Opp" }, { label: "TOI" }, { label: "SA", hl: stat === "sog" }, { label: "SV", hl: stat === "saves" },
          { label: "GA", hl: stat === "goals_against" }, { label: "SV%" }],
        rows: games.map((g) => ({
          key: g.game_id,
          cells: [dateCell(g), oppCell(g), { v: clock(g.toi), cls: g.toi < PARTIAL_GAME_SECONDS ? "pl-c-strong" : undefined },
            numCell(g.shots_against), numCell(g.saves), numCell(g.goals_against), textCell(savePct(g.saves, g.shots_against))],
        })),
        foot: [{ v: "Total" }, blankCell, textCell((gaa(games) ?? 0).toFixed(2), "GAA"),
          { v: String(total(games, (g) => g.shots_against)) }, { v: String(total(games, (g) => g.saves)) },
          { v: String(total(games, (g) => g.goals_against)) }, { v: svPctOf(games) }],
      }),
    },
    {
      id: "shots",
      label: "Shot quality",
      caption: "xGA is the goals an average goalie would allow on these shots; GSAx is goals saved above that. HD is high danger.",
      table: (games): TableSpec => {
        const xga = total(games, (g) => g.x_goals_against) ?? 0;
        return {
          label: "Shot quality by start",
          grid: "70px 88px repeat(7, minmax(64px, 1fr))",
          minWidth: 760,
          cols: ["Date", "Opp", "HD shots", "HD xG", "xGA", "GA", "GSAx", "Rebounds", "xRebounds"].map((label) => ({ label })),
          rows: games.map((g) => ({
            key: g.game_id,
            cells: [dateCell(g), oppCell(g), numCell(g.high_danger_shots), textCell(g.high_danger_x_goals.toFixed(2)),
              textCell(g.x_goals_against.toFixed(2)), numCell(g.goals_against),
              { v: signed(g.x_goals_against - g.goals_against, 2), cls: g.goals_against > g.x_goals_against ? "pl-c-dim" : undefined },
              numCell(g.rebounds), textCell(g.x_rebounds.toFixed(1))],
          })),
          foot: [{ v: "Total" }, blankCell, { v: String(total(games, (g) => g.high_danger_shots)) },
            { v: (total(games, (g) => g.high_danger_x_goals) ?? 0).toFixed(1) }, { v: xga.toFixed(1) },
            { v: String(total(games, (g) => g.goals_against)) }, { v: signed(gsax(games), 1) },
            { v: String(total(games, (g) => g.rebounds)) }, { v: (total(games, (g) => g.x_rebounds) ?? 0).toFixed(1) }],
        };
      },
    },
    {
      id: "model",
      label: "Model vs result",
      caption: "Each result over what the model expected before puck drop. Grey means a worse night than the model expected; starts it didn't log show no number.",
      table: (games): TableSpec => ({
        label: "Model against result by start",
        grid: "70px 88px repeat(3, minmax(80px, 1fr))",
        minWidth: 480,
        cols: [{ label: "Date" }, { label: "Opp" }, ...statCols],
        rows: games.map((g) => ({
          key: g.game_id,
          cells: [dateCell(g), oppCell(g), ...GOALIE_STATS.map((d): Cell => {
            const v = d.value(g);
            const e = g.expected[d.key];
            if (v === null || e === undefined) return numCell(v);
            const worse = d.lowerIsBetter ? v > e : v < e;
            return { v: String(v), exp: e.toFixed(1), cls: worse ? "pl-c-dim" : undefined };
          })],
        })),
        foot: [{ v: "Total" }, blankCell, ...GOALIE_STATS.map((d) => modelFoot(games, d))],
      }),
    },
    {
      id: "splits",
      label: "Splits",
      caption: "Per-start averages by split; SV%, GAA and GSAx over the whole split.",
      filterable: false,
      table: (games): TableSpec => {
        const groups: [string, GoalieGame[]][] = [["All starts", games], ["Home", games.filter((g) => g.home_away === "HOME")],
          ["Away", games.filter((g) => g.home_away === "AWAY")], ["Last 10", games.slice(-10)], ["Last 5", games.slice(-5)]];
        return {
          label: "Averages by split",
          grid: "110px 48px repeat(6, minmax(60px, 1fr))",
          minWidth: 600,
          cols: [{ label: "Split" }, { label: "GP" }, { label: "SA", hl: stat === "sog" }, { label: "SV", hl: stat === "saves" },
            { label: "GA", hl: stat === "goals_against" }, { label: "SV%" }, { label: "GAA" }, { label: "GSAx" }],
          rows: groups.filter(([, gs]) => gs.length).map(([name, gs]) => ({
            key: name,
            cells: [{ v: name }, { v: String(gs.length), cls: "pl-c-date" }, textCell(avg(gs, (g) => g.shots_against)),
              textCell(avg(gs, (g) => g.saves)), textCell(avg(gs, (g) => g.goals_against)), textCell(svPctOf(gs)),
              textCell((gaa(gs) ?? 0).toFixed(2)), textCell(signed(gsax(gs), 1))],
          })),
        };
      },
    },
  ];
};

export const goalieSeasonLine = (games: GoalieGame[]) => {
  const g = gaa(games);
  return [
    { label: "GP", value: String(games.length) },
    { label: "SV%", value: svPctOf(games) },
    { label: "GAA", value: g === null ? "—" : g.toFixed(2) },
    { label: "GSAx", value: games.length ? signed(gsax(games), 1) : "—" },
  ];
};
