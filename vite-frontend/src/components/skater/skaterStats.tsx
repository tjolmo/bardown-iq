import type { PlayerPropData } from "../../types/player";
import type { SkaterGame, SkaterGamePredictions } from "../../types/skater";
import { atLeastOne, clock, perGame, signed, total, type StatDef } from "../../utils/playerStats";
import { blankCell, dateCell, modelFoot, numCell, oppCell, textCell } from "../player/cells";
import type { SeasonView } from "../player/SeasonLog";
import type { Cell, TableSpec } from "../player/StatTable";

/** Every stat the skater models predict (backend predictions/config.py SKATER_TARGETS). */
export const SKATER_STATS: StatDef<SkaterGame>[] = [
  { key: "goals", label: "Goals", short: "G", one: "goal", many: "goals", value: (g) => g.goals, propTypes: ["player_goals", "player_goal_scorer_anytime"] },
  { key: "assists", label: "Assists", short: "A", one: "assist", many: "assists", value: (g) => g.assists, propTypes: ["player_assists"] },
  { key: "points", label: "Points", short: "PTS", one: "point", many: "points", value: (g) => g.points, propTypes: ["player_points"] },
  { key: "shots_on_goal", label: "Shots on goal", short: "SOG", one: "shot", many: "shots", value: (g) => g.shots_on_goal, propTypes: ["player_shots_on_goal"] },
  { key: "hits", label: "Hits", short: "HIT", one: "hit", many: "hits", value: (g) => g.hits, propTypes: ["player_hits"] },
  { key: "blocked_shots", label: "Blocked shots", short: "BLK", one: "block", many: "blocks", value: (g) => g.blocked_shots, propTypes: ["player_blocked_shots"] },
  // not priced: the model counts 5-on-4 points only, books settle on every power play (backend predict.PROP_STATS)
  { key: "pp_points", label: "Power-play points", short: "PPP", one: "PP point", many: "PP points", value: (g) => g.pp_points, propTypes: [] },
];

export const DEFAULT_SKATER_STAT = "points";

export const skaterExpected = (p: SkaterGamePredictions | null, key: string): number | null => {
  const v = p ? p[key as keyof SkaterGamePredictions] : null;
  return typeof v === "number" ? v : null;
};

const API_PROBS: Record<string, keyof SkaterGamePredictions> = { goals: "prob_goal", assists: "prob_assist", points: "prob_point" };

/** The model's chance at the book's main line for this stat when a prop is posted ("Over 3.5"), else its chance of
 *  at least one. */
export const chanceAtLine = (def: StatDef<SkaterGame>, props: PlayerPropData[], p: SkaterGamePredictions | null) => {
  const priced = props
    .filter((x) => def.propTypes.includes(x.prop_type) && x.model_prob !== null && ["OVER", "YES"].includes(x.over_under.toUpperCase()))
    .sort((a, b) => a.line - b.line);
  if (priced.length) {
    const x = priced[0];
    const oneOrMore = x.over_under.toUpperCase() === "YES" || x.line < 1;
    return { p: x.model_prob!, label: oneOrMore ? "Chance of 1+" : `Over ${x.line}` };
  }
  const fromApi = API_PROBS[def.key] && p ? p[API_PROBS[def.key]] : null;
  if (typeof fromApi === "number") return { p: fromApi, label: "Chance of 1+" };
  const mean = skaterExpected(p, def.key);
  return mean !== null ? { p: atLeastOne(mean), label: "Chance of 1+" } : null;
};

const onIcePct = (v: number) => `${(v <= 1 ? v * 100 : v).toFixed(1)}%`;
const avg = (games: SkaterGame[], f: (g: SkaterGame) => number | null, digits = 2) => {
  const v = perGame(games, f);
  return v === null ? "—" : v.toFixed(digits);
};

/** The season tab's views of every game. `stat` is the picked stat's key, highlighted where it has a column. */
export const skaterSeasonViews = (stat: string): SeasonView<SkaterGame>[] => {
  const statCols = SKATER_STATS.map((d) => ({ label: d.short, hl: d.key === stat }));
  return [
    {
      id: "box",
      label: "Box score",
      caption: "Every game, newest first. A1 and A2 are primary and secondary assists; PP TOI is 5-on-4 ice time.",
      table: (games): TableSpec => {
        const keys: [string, string, (g: SkaterGame) => number | null][] = [
          ["G", "goals", (g) => g.goals], ["A1", "", (g) => g.primary_assists], ["A2", "", (g) => g.secondary_assists],
          ["A", "assists", (g) => g.assists], ["PTS", "points", (g) => g.points], ["SOG", "shots_on_goal", (g) => g.shots_on_goal],
          ["HIT", "hits", (g) => g.hits], ["BLK", "blocked_shots", (g) => g.blocked_shots], ["PPP", "pp_points", (g) => g.pp_points],
        ];
        return {
          label: "Box score by game",
          grid: "70px 88px 64px repeat(9, minmax(44px, 1fr)) 64px",
          minWidth: 900,
          cols: [{ label: "Date" }, { label: "Opp" }, { label: "TOI" }, ...keys.map(([label, key]) => ({ label, hl: key === stat })), { label: "PP TOI" }],
          rows: games.map((g) => ({
            key: g.game_id,
            cells: [dateCell(g), oppCell(g), textCell(clock(g.toi)), ...keys.map(([, , f]) => numCell(f(g))), textCell(g.pp_toi === null ? "—" : clock(g.pp_toi))],
          })),
          foot: [{ v: "Total" }, blankCell, textCell(clock(perGame(games, (g) => g.toi) ?? 0), "avg"),
            ...keys.map(([, , f]): Cell => ({ v: String(total(games, f) ?? "—") })),
            textCell(clock(perGame(games, (g) => g.pp_toi) ?? 0), "avg")],
        };
      },
    },
    {
      id: "shots",
      label: "Shot quality",
      caption: "Att is shot attempts, HD high-danger shots, xG expected goals from those shots, OI xG% the share of expected goals for while on the ice.",
      table: (games): TableSpec => {
        const xg = total(games, (g) => g.x_goals) ?? 0;
        const goals = total(games, (g) => g.goals) ?? 0;
        return {
          label: "Shot quality by game",
          grid: "70px 88px repeat(8, minmax(60px, 1fr))",
          minWidth: 820,
          cols: ["Date", "Opp", "Att", "SOG", "HD", "xG", "G", "G−xG", "OI xG%", "Game score"].map((label) => ({ label })),
          rows: games.map((g) => ({
            key: g.game_id,
            cells: [dateCell(g), oppCell(g), numCell(g.shot_attempts), numCell(g.shots_on_goal), numCell(g.high_danger_shots),
              textCell(g.x_goals.toFixed(2)), numCell(g.goals),
              { v: signed(g.goals - g.x_goals, 2), cls: g.goals < g.x_goals ? "pl-c-dim" : undefined },
              textCell(onIcePct(g.on_ice_x_goals_percentage)), textCell(g.game_score.toFixed(2))],
          })),
          foot: [{ v: "Total" }, blankCell, { v: String(total(games, (g) => g.shot_attempts)) }, { v: String(total(games, (g) => g.shots_on_goal) ?? "—") },
            { v: String(total(games, (g) => g.high_danger_shots)) }, { v: xg.toFixed(1) }, { v: String(goals) }, { v: signed(goals - xg, 1) },
            textCell(onIcePct(perGame(games, (g) => g.on_ice_x_goals_percentage) ?? 0), "avg"), textCell(avg(games, (g) => g.game_score), "avg")],
        };
      },
    },
    {
      id: "model",
      label: "Model vs result",
      caption: "Each result over what the model expected before puck drop. Grey means the night fell short of the model; games it didn't log show no number.",
      table: (games): TableSpec => ({
        label: "Model against result by game",
        grid: `70px 88px repeat(${SKATER_STATS.length}, minmax(64px, 1fr))`,
        minWidth: 720,
        cols: [{ label: "Date" }, { label: "Opp" }, ...statCols],
        rows: games.map((g) => ({
          key: g.game_id,
          cells: [dateCell(g), oppCell(g), ...SKATER_STATS.map((d): Cell => {
            const v = d.value(g);
            const e = g.expected[d.key];
            if (v === null || e === undefined) return numCell(v);
            return { v: String(v), exp: e.toFixed(2), cls: v < e ? "pl-c-dim" : undefined };
          })],
        })),
        foot: [{ v: "Total" }, blankCell, ...SKATER_STATS.map((d): Cell => modelFoot(games, d))],
      }),
    },
    {
      id: "splits",
      label: "Splits",
      caption: "Per-game averages by split.",
      filterable: false,
      table: (games): TableSpec => {
        const groups: [string, SkaterGame[]][] = [["All games", games], ["Home", games.filter((g) => g.home_away === "HOME")],
          ["Away", games.filter((g) => g.home_away === "AWAY")], ["Last 10", games.slice(-10)], ["Last 5", games.slice(-5)]];
        return {
          label: "Per-game averages by split",
          grid: `110px 48px repeat(${SKATER_STATS.length}, minmax(52px, 1fr)) 64px`,
          minWidth: 700,
          cols: [{ label: "Split" }, { label: "GP" }, ...statCols, { label: "TOI" }],
          rows: groups.filter(([, gs]) => gs.length).map(([name, gs]) => ({
            key: name,
            cells: [{ v: name }, { v: String(gs.length), cls: "pl-c-date" }, ...SKATER_STATS.map((d) => textCell(avg(gs, d.value))),
              textCell(clock(perGame(gs, (g) => g.toi) ?? 0))],
          })),
        };
      },
    },
  ];
};

