import type { FC } from "react";
import { Link } from "react-router-dom";
import type { TeamScheduledGame } from "../../types/teams";
import { formatAmerican, localTime, splitTeamName } from "../../utils/gameStatus";
import { RinkMeter } from "./RinkMeter";
import { EdgeChip } from "./EdgeChip";

interface ScheduleRowProps {
  game: TeamScheduledGame;
  // the followed team plays at home
  home: boolean;
  backToBack: boolean;
}

/** One game on a team's schedule: the day, the opponent, puck drop, the model's odds, the Vegas line and the edge. */
export const ScheduleRow: FC<ScheduleRowProps> = ({ game, home, backToBack }) => {
  const opponent = home ? game.awayTeam : game.homeTeam;
  const { city, nickname } = splitTeamName(opponent.name);
  const d = new Date(game.time);
  const awayProb = game.predictions?.away.prob_win ?? null;
  const edgeTeam = game.edge ? (game.edge.side === "home" ? game.homeTeam : game.awayTeam) : null;

  return (
    <li className="bd-sched-row" aria-label={`${home ? "vs" : "at"} ${opponent.name}`}>
      <div className="bd-sched-date">
        <span className="bd-label">{d.toLocaleDateString("en-US", { weekday: "short" })}</span>
        <span className="bd-score">{d.getDate()}</span>
        <span className="bd-label">{d.toLocaleDateString("en-US", { month: "short" })}</span>
      </div>

      <Link to={`/schedule/team/${opponent.tricode}`} className="bd-sched-opp">
        <img src={opponent.logoUrl} alt={opponent.name} />
        <div style={{ minWidth: 0 }}>
          <div className="bd-row" style={{ gap: 8 }}>
            <span className="bd-label" style={{ color: "var(--ink)" }}>{home ? "VS" : "AT"}</span>
            {city && <span className="bd-team-city">{city}</span>}
          </div>
          <div className="bd-team-name">{nickname}</div>
          <div className="bd-muted" style={{ fontSize: 13, marginTop: 2 }}>{game.venue}</div>
        </div>
      </Link>

      <div className="bd-sched-status">
        <span className="bd-chip bd-chip-time">{localTime(game.time)}</span>
        {backToBack && <span className="bd-chip bd-chip-quiet">BACK-TO-BACK</span>}
      </div>

      <div className="bd-sched-meter">
        {awayProb !== null ? (
          <RinkMeter
            away={awayProb}
            label="Model win %"
            tricodes={{ away: game.awayTeam.tricode, home: game.homeTeam.tricode }}
          />
        ) : (
          <p className="bd-label" style={{ margin: 0, textAlign: "center" }}>No model odds for this game yet</p>
        )}
      </div>

      <div className="bd-sched-line">
        {game.moneyline ? (
          <span>
            Vegas <strong>{game.awayTeam.tricode} {formatAmerican(game.moneyline.away)}</strong>
            {" / "}
            <strong>{game.homeTeam.tricode} {formatAmerican(game.moneyline.home)}</strong>
          </span>
        ) : (
          <span>No line posted yet</span>
        )}
        {game.edge && edgeTeam && (
          <EdgeChip tricode={edgeTeam.tricode} logoUrl={edgeTeam.logoUrl} points={game.edge.points} />
        )}
      </div>
    </li>
  );
};
