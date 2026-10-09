import type { FC } from "react";
import type { TeamScheduledGame } from "../../types/teams";

// the chart's tallest bar (100%) in px; the 50% line sits at half of it
const BAR_SCALE = 180;

export interface StretchGame {
  game: TeamScheduledGame;
  home: boolean;
  // the followed team's model win probability, 0-1, or null with no odds yet
  winProb: number | null;
}

interface StretchChartProps {
  // the nickname: "Maple Leafs"
  teamName: string;
  games: StretchGame[];
  // the coach's note under the chart, if any
  note?: string | null;
}

const opponentTag = ({ game, home }: StretchGame): string =>
  home ? `vs ${game.awayTeam.tricode}` : `@ ${game.homeTeam.tricode}`;

const tickDate = (iso: string): string =>
  new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });

/** The followed team's model win % for each game coming up: red bars at home, blue on the road, against 50%. */
export const StretchChart: FC<StretchChartProps> = ({ teamName, games, note }) => (
  <article className="bd-card" aria-labelledby="stretch-title">
    <div className="bd-section-head" style={{ gap: "8px 24px" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span className="bd-label" style={{ alignSelf: "flex-start" }}>
          Model win % for the {teamName}, game by game
        </span>
        <h3 id="stretch-title" className="bd-heading" style={{ fontSize: 28 }}>
          The stretch
        </h3>
      </div>
      <div className="bd-legend">
        <span>
          <i className="bd-swatch" style={{ background: "var(--goal-red)", borderRadius: 3 }} />
          At home
        </span>
        <span>
          <i className="bd-swatch" style={{ background: "var(--blue-line)", borderRadius: 3 }} />
          On the road
        </span>
      </div>
    </div>

    <div>
      <div className="bd-chart">
        <div className="bd-chart-mid" style={{ bottom: BAR_SCALE / 2 }} aria-hidden="true">
          <span>50%</span>
        </div>
        <div className="bd-chart-cols">
          {games.map((g) => {
            const pct = g.winProb === null ? null : Math.round(g.winProb * 100);
            const title =
              pct === null
                ? `${opponentTag(g)}, ${tickDate(g.game.time)}: no model odds yet`
                : `${opponentTag(g)}, ${tickDate(g.game.time)}: ${teamName} ${pct}%`;
            return (
              <div key={g.game.id} className="bd-chart-col" title={title} aria-label={title} role="img">
                {pct === null ? (
                  <>
                    <span style={{ color: "var(--ink-subtle)" }}>–</span>
                    <div className="bd-chart-bar" style={{ height: 2, background: "var(--line)" }} />
                  </>
                ) : (
                  <>
                    <span>{pct}%</span>
                    <div
                      className="bd-chart-bar"
                      style={{
                        height: Math.round((pct / 100) * BAR_SCALE),
                        background: g.home ? "var(--goal-red)" : "var(--blue-line)",
                      }}
                    />
                  </>
                )}
              </div>
            );
          })}
        </div>
      </div>
      <div className="bd-chart-ticks" aria-hidden="true">
        {games.map((g) => (
          <span key={g.game.id}>
            <strong>{opponentTag(g)}</strong>
            {tickDate(g.game.time)}
          </span>
        ))}
      </div>
    </div>

    {note && (
      <span className="bd-note" style={{ fontSize: 19, alignSelf: "flex-end" }}>
        {note}
      </span>
    )}
  </article>
);
