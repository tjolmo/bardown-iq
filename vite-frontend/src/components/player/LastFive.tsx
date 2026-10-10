import type { ReactNode } from "react";
import type { TeamLookup } from "../../types/teams";
import { gameDay, total, teamOf, where, type PlayerGame, type StatDef } from "../../utils/playerStats";
import { blankCell, dateCell, numCell, oppCell } from "./cells";
import { StatTable, type Cell, type TableSpec } from "./StatTable";

export interface NextGame {
  tricode: string;
  home: boolean;
  time: string | null;
}

export interface ExtraCol<G> {
  label: string;
  value: (g: G) => string;
  foot: (games: G[]) => string;
}

interface LastFiveProps<G extends PlayerGame> {
  games: G[];                           // oldest first
  defs: StatDef<G>[];
  stat: StatDef<G>;
  picker: ReactNode;
  expectedNext: number | null;          // the model's number for the picked stat next game
  next: NextGame | null;
  teams: TeamLookup;
  extraCols?: ExtraCol<G>[];
}

const CHART_HEIGHT = 170;

const fmtExpected = (x: number) => (x < 10 ? x.toFixed(2) : x.toFixed(1));

/** The picked stat over the last five games as bars, the model's number for the next game as a dashed bar and line,
 *  and the five games' log beside it with every stat the model predicts. */
export function LastFive<G extends PlayerGame>({ games, defs, stat, picker, expectedNext, next, teams, extraCols = [] }: LastFiveProps<G>) {
  const vals = games.map(stat.value);
  const top = Math.max(...vals.map((v) => v ?? 0), expectedNext ?? 0, 1) * 1.1;
  const px = (v: number) => Math.round((v / top) * CHART_HEIGHT);
  const sum = total(games, stat.value);

  const spec: TableSpec = {
    label: "Last five games",
    grid: `56px 78px repeat(${defs.length + extraCols.length}, minmax(36px, 1fr))`,
    minWidth: 160 + 44 * (defs.length + extraCols.length),
    cols: [{ label: "Date" }, { label: "Opp" }, ...defs.map((d) => ({ label: d.short, hl: d.key === stat.key })),
      ...extraCols.map((c) => ({ label: c.label }))],
    rows: [...games].reverse().map((g, i) => ({
      key: `${g.date}-${i}`,
      cells: [dateCell(g), oppCell(g), ...defs.map((d) => numCell(d.value(g))), ...extraCols.map((c): Cell => ({ v: c.value(g) }))],
    })),
    foot: [{ v: `Last ${games.length}` }, blankCell,
      ...defs.map((d): Cell => ({ v: String(total(games, d.value) ?? "—") })),
      ...extraCols.map((c): Cell => ({ v: c.foot(games) }))],
  };

  return (
    <section className="bd-section" aria-labelledby="last-h">
      <div className="bd-section-head">
        <h2 className="bd-heading" id="last-h">Last {games.length === 5 ? "five" : games.length}</h2>
        {picker}
      </div>
      <div className="pl-split">
        <div className="pl-panel">
          <div className="bd-legend">
            <span><i className="bd-swatch" style={{ background: "var(--ink)" }} />{stat.label}</span>
            {expectedNext !== null && (
              <span><i className="bd-swatch" style={{ border: "2px dashed var(--ink)", boxSizing: "border-box" }} />Model, next game</span>
            )}
          </div>
          <div className="pl-bars" role="img"
            aria-label={`${stat.label} in the last games: ${vals.map((v) => v ?? "no data").join(", ")}.` +
              (expectedNext !== null ? ` The model expects ${fmtExpected(expectedNext)} next game.` : "")}>
            {expectedNext !== null && (
              <div className="pl-proj" style={{ bottom: px(expectedNext) }}><span>{fmtExpected(expectedNext)} EXP</span></div>
            )}
            {vals.map((v, i) => (
              <div key={i} className={`pl-bar-col${!v ? " pl-c-dim" : ""}`}>
                {v ?? "—"}
                {v ? <div className="pl-bar" style={{ height: px(v) }} /> : null}
              </div>
            ))}
            {expectedNext !== null && (
              <div className="pl-bar-col">?<div className="pl-ghost" style={{ height: px(expectedNext) }} /></div>
            )}
          </div>
          <div className="pl-ticks" aria-hidden="true">
            {games.map((g, i) => (
              <span key={i}>
                <img src={teamOf(teams, g.opposing_team_tricode).logoUrl} alt="" />
                <strong>{where(g)} {g.opposing_team_tricode}</strong>{gameDay(g.date)}
              </span>
            ))}
            {expectedNext !== null && next && (
              <span>
                <img src={teamOf(teams, next.tricode).logoUrl} alt="" />
                <strong>{next.home ? "vs" : "@"} {next.tricode}</strong>Next
              </span>
            )}
          </div>
          {sum !== null && games.length > 1 && (
            <span className="bd-note">{sum} {sum === 1 ? stat.one : stat.many} in {games.length}</span>
          )}
        </div>
        <div className="pl-panel">
          <span className="bd-label" style={{ alignSelf: "flex-start" }}>Game log</span>
          <div className="pl-flush-box">
            <StatTable spec={spec} flush />
          </div>
        </div>
      </div>
    </section>
  );
}
