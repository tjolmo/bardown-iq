import type { FC } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { RinkHero } from "../components/rinkboard/RinkHero";
import { LinesBoard } from "../components/roster/LinesBoard";
import { LineupChanges } from "../components/roster/LineupChanges";
import { OutOfLineup } from "../components/roster/OutOfLineup";
import { RosterTable } from "../components/roster/RosterTable";
import { useRoster } from "../hooks/useRoster";
import type { LineupGame, TeamLineup } from "../types/lineup";
import type { TeamLookup } from "../types/teams";
import { daysBetween, localTime, shortDay, splitTeamName } from "../utils/gameStatus";
import { tonightRoles } from "../utils/lineup";
import { teamOf } from "../utils/playerStats";

type View = "lines" | "roster";

const STARTED = new Set(["LIVE", "CRIT", "FINAL", "OFF"]);

/** "Tonight", "Tomorrow" or "SAT · OCT 10", in the visitor's time zone. */
const gameDay = (iso: string): string => {
  const days = daysBetween(new Date().toISOString(), iso);
  return days === 0 ? "Tonight" : days === 1 ? "Tomorrow" : shortDay(iso);
};

const linesHeading = (game: LineupGame | null): string => {
  if (!game) return "Last lineup";
  const day = gameDay(game.startTime);
  return day === "Tonight" ? "Tonight's lines" : day === "Tomorrow" ? "Tomorrow's lines" : `Lines · ${day}`;
};

const statusNote = (lineup: TeamLineup): string => {
  const games = lineup.basedOn.length;
  const from = `the last ${games === 1 ? "game's" : `${games} games'`} NHL shift charts`;
  if (lineup.status === "projected") {
    return `Projected from ${from}${lineup.injuryReportAsOf ? " and ESPN's injury report" : ""}. ` +
      "The NHL posts the lineup about an hour before puck drop.";
  }
  if (lineup.game && STARTED.has(lineup.game.gameState)) {
    return `The dressed players are the NHL's. Lines are projected from ${from} until this game's chart is in.`;
  }
  return `The NHL has posted the dressed players. Lines stay projected from ${from} until puck drop.`;
};

const NextGame: FC<{ game: LineupGame | null; teams: TeamLookup; tricode: string }> = ({ game, teams, tricode }) => {
  const schedule = (
    <Link to={`/schedule/team/${tricode}`} className="bd-btn" style={{ marginTop: 6 }}>
      Schedule
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true">
        <path d="M9 5l7 7-7 7" />
      </svg>
    </Link>
  );
  if (!game) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
        <span className="bd-label">Next game</span>
        <span className="bd-muted" style={{ fontWeight: 600 }}>None scheduled</span>
        {schedule}
      </div>
    );
  }
  const opp = teamOf(teams, game.opponent);
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
      <span className="bd-label">Next game</span>
      <div className="rs-hero-next">
        <span className="bd-display-xl">{game.home ? "Vs" : "At"} {splitTeamName(opp.name).city || opp.tricode}</span>
        <img src={opp.logoUrl} alt={opp.name} />
      </div>
      <span className="bd-muted" style={{ fontWeight: 600 }}>
        {[gameDay(game.startTime), localTime(game.startTime), game.venue].filter(Boolean).join(" · ")}
      </span>
      {schedule}
    </div>
  );
};

/** A team's page: the next game's lines (projected from shift charts, or posted by the NHL), who's out, and the
 *  whole roster on its own tab. */
export const RosterPage: FC = () => {
  const { tricode: param } = useParams<{ tricode: string }>();
  const tricode = param!.toUpperCase();
  const [params, setParams] = useSearchParams();
  const view: View = params.get("view") === "roster" ? "roster" : "lines";
  const { roster, lineup, teams, loading, lineupLoading, error, lineupError } = useRoster(tricode);

  const lookup: TeamLookup = Object.fromEntries((teams ?? []).map((t) => [t.tricode, t]));
  const team = teamOf(lookup, tricode);
  const { city, nickname } = teams ? splitTeamName(team.name) : { city: "", nickname: tricode };
  const setView = (v: View) => setParams(v === "lines" ? {} : { view: v }, { replace: true });
  const hasLines = !!lineup && lineup.forwards.length > 0;

  return (
    <div className="bd-page">
      <main className="bd-main">
        <RinkHero
          labelledBy="team-title"
          left={
            <>
              <div className="bd-row" style={{ gap: 8 }}>
                <Link to="/teams" className="bd-icon-btn" aria-label="All teams">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true">
                    <path d="M15 5l-7 7 7 7" />
                  </svg>
                </Link>
                <span className="bd-muted" style={{ fontWeight: 700 }}>Roster{city && ` · ${city}`}</span>
              </div>
              <div className="bd-row" style={{ gap: 16 }}>
                <img className="bd-team-logo" src={team.logoUrl} alt={team.name} />
                <h1 id="team-title" className="bd-display-xl">
                  {nickname.split(" ").map((word, i) => (
                    <span key={i}>
                      {i > 0 && <br />}
                      {word}
                    </span>
                  ))}
                </h1>
              </div>
            </>
          }
          right={lineup ? <NextGame game={lineup.game} teams={lookup} tricode={tricode} /> : (
            <Link to={`/schedule/team/${tricode}`} className="bd-btn">Schedule</Link>
          )}
        />

        <div className="rs-tabs">
          <div className="rs-seg" role="group" aria-label="View">
            <button type="button" aria-pressed={view === "lines"} onClick={() => setView("lines")}>Lines</button>
            <button type="button" aria-pressed={view === "roster"} onClick={() => setView("roster")}>
              Roster {roster && <span className="rs-seg-count">{roster.length}</span>}
            </button>
          </div>
          <span className="rs-note" style={{ fontWeight: 600 }}>Lines rebuilt from NHL shift charts after every game</span>
        </div>

        {view === "lines" && (
          lineupLoading ? (
            <p className="bd-empty" role="status">Drawing up the lines</p>
          ) : lineupError || !lineup ? (
            <p className="bd-empty" role="alert">The lines didn't load. Check that the API is up, then refresh the page.</p>
          ) : (
            <>
              <section className="bd-section" aria-labelledby="lines-heading">
                <div className="bd-section-head">
                  <div className="bd-row" style={{ gap: 16 }}>
                    <h2 id="lines-heading" className="bd-heading">{linesHeading(lineup.game)}</h2>
                    {hasLines && (
                      <span className={`bd-chip ${lineup.status === "confirmed" ? "bd-chip-final" : "bd-chip-time"}`}>
                        {lineup.status === "confirmed" ? "LINEUP POSTED" : "PROJECTED"}
                      </span>
                    )}
                  </div>
                  {hasLines && <span className="rs-note">{statusNote(lineup)}</span>}
                </div>
                {hasLines ? (
                  <>
                    <LineupChanges lineup={lineup} />
                    <LinesBoard lineup={lineup} />
                  </>
                ) : (
                  <p className="bd-empty">
                    No lines yet. They're rebuilt from the NHL's shift charts once the team has played a game.
                  </p>
                )}
              </section>

              <section className="bd-section" aria-labelledby="out-heading">
                <div className="bd-section-head">
                  <h2 id="out-heading" className="bd-heading">Out of the lineup</h2>
                  <span className="rs-note">
                    {lineup.injuryReportAsOf
                      ? `Injury report from ESPN, as of ${localTime(lineup.injuryReportAsOf)}. `
                      : "No recent injury report from ESPN. "}
                    Scratches from the NHL's game sheet.
                  </span>
                </div>
                <OutOfLineup lineup={lineup} posted={lineup.status === "confirmed"} />
              </section>
            </>
          )
        )}

        {view === "roster" && (
          loading ? (
            <p className="bd-empty" role="status">Loading the roster</p>
          ) : error || !roster ? (
            <p className="bd-empty" role="alert">The roster didn't load. Check that the API is up, then refresh the page.</p>
          ) : (
            <RosterTable players={roster} roles={hasLines ? tonightRoles(lineup!) : null} />
          )
        )}
      </main>
    </div>
  );
};

export default RosterPage;
