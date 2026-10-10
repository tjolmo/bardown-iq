import { useState } from "react";
import type { PlayerGame } from "../../utils/playerStats";
import { StatTable, type TableSpec } from "./StatTable";

export interface SeasonView<G> {
  id: string;
  label: string;
  caption: string;
  // the table for these games, newest first (all of them when the view ignores the home/away filter)
  table: (games: G[]) => TableSpec;
  filterable?: boolean;
}

type Venue = "ALL" | "HOME" | "AWAY";
const VENUES: [Venue, string][] = [["ALL", "All"], ["HOME", "Home"], ["AWAY", "Away"]];

/** Every game of the season in one scrolling table, seen several ways (box score, shot quality, the model against
 *  the result, splits), filtered to home or away games. */
export function SeasonLog<G extends PlayerGame>({ games, views, noun }: { games: G[]; views: SeasonView<G>[]; noun: [string, string] }) {
  const [viewId, setViewId] = useState(views[0].id);
  const [venue, setVenue] = useState<Venue>("ALL");
  const view = views.find((v) => v.id === viewId) ?? views[0];
  const filterable = view.filterable !== false;
  const shown = (filterable && venue !== "ALL" ? games.filter((g) => g.home_away === venue) : games).slice().reverse();
  const home = games.filter((g) => g.home_away === "HOME").length;
  const count = (n: number) => `${n} ${n === 1 ? noun[0] : noun[1]}`;

  return (
    <section className="bd-section" aria-labelledby="season-h">
      <div className="bd-section-head">
        <h2 className="bd-heading" id="season-h">The season, {noun[0]} by {noun[0]}</h2>
        <span className="bd-muted">{count(games.length)} · {home} home · {games.length - home} away</span>
      </div>
      {games.length === 0 ? (
        <div className="bd-empty">No {noun[1]} this season yet.</div>
      ) : (
        <>
          <div className="pl-season-bar">
            <div className="pl-tabs" role="tablist" aria-label="Season view">
              {views.map((v) => (
                <button key={v.id} type="button" className="pl-tab" role="tab" aria-selected={v.id === view.id}
                  onClick={() => setViewId(v.id)}>
                  {v.label}
                </button>
              ))}
            </div>
            {filterable && (
              <div className="pl-filters" role="group" aria-label="Which games">
                {VENUES.map(([id, label]) => (
                  <button key={id} type="button" className="pl-filter" aria-pressed={venue === id} onClick={() => setVenue(id)}>
                    {label}
                  </button>
                ))}
              </div>
            )}
          </div>
          <p className="pl-caption">{view.caption}</p>
          <div className="pl-scroll" role="tabpanel">
            {shown.length ? <StatTable spec={view.table(filterable ? shown : games)} /> : <div className="bd-empty" style={{ border: 0 }}>No {noun[1]} here.</div>}
          </div>
        </>
      )}
    </section>
  );
}
