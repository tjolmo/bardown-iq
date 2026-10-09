import type { FC } from "react";
import type { TeamScheduledGame } from "../../types/teams";
import { formatAmerican, gamePhase, shortDay, statusChip } from "../../utils/gameStatus";
import { StatusChip } from "./StatusChip";
import { TeamMark } from "./TeamMark";
import { RinkMeter } from "./RinkMeter";
import { EdgeChip } from "./EdgeChip";

interface BoardGameCardProps {
  game: TeamScheduledGame;
  // the day's single best pick gets the coach's ring
  coachsPick?: boolean;
  // the puck-drop chip also names the day, for a card off the day's board
  showDate?: boolean;
  // when the games were fetched and the current time (ms), for the intermission countdown
  receivedAt: number;
  now: number;
}

/** One game on the board: status, both teams, score or AT, the model's odds, the Vegas line and the edge. */
export const BoardGameCard: FC<BoardGameCardProps> = ({ game, coachsPick = false, showDate = false, receivedAt, now }) => {
  const phase = gamePhase(game);
  const status = statusChip(game, receivedAt, now);
  const chip = showDate && status.kind === "time" ? { ...status, text: `${shortDay(game.time)} · ${status.text}` } : status;
  const started = phase !== "pre";
  const hasScore = started && game.awayScore !== null && game.homeScore !== null;
  const awayProb = game.predictions?.away.prob_win ?? null;
  const edgeTeam = game.edge ? (game.edge.side === "home" ? game.homeTeam : game.awayTeam) : null;

  return (
    <article className="bd-card" aria-label={`${game.awayTeam.name} at ${game.homeTeam.name}`}>
      <div className="bd-card-top">
        <StatusChip status={chip} />
        <span>{game.venue}</span>
      </div>

      <div className="bd-card-teams">
        <TeamMark team={game.awayTeam} />
        <div className="bd-card-mid">
          {hasScore ? (
            <span className="bd-score" aria-label={`${game.awayScore} to ${game.homeScore}`}>
              {game.awayScore}–{game.homeScore}
            </span>
          ) : (
            <span className="bd-label">AT</span>
          )}
        </div>
        <TeamMark team={game.homeTeam} home />
      </div>

      {awayProb !== null ? (
        <RinkMeter away={awayProb} label={started ? "Pre-game model win %" : "Model win %"} />
      ) : (
        <p className="bd-label" style={{ margin: 0, textAlign: "center" }}>
          {started ? "No pre-game prediction was logged for this game" : "No model odds for this game yet"}
        </p>
      )}

      {(game.moneyline || (game.edge && edgeTeam)) && (
        <div className="bd-card-foot">
          {game.moneyline ? (
            <span>
              {started ? "Closing" : "Vegas"} <strong>{game.awayTeam.tricode} {formatAmerican(game.moneyline.away)}</strong>
              {" / "}
              <strong>{game.homeTeam.tricode} {formatAmerican(game.moneyline.home)}</strong>
            </span>
          ) : (
            <span />
          )}
          {game.edge && edgeTeam && (
            <span style={{ position: "relative", display: "inline-flex" }}>
              <EdgeChip tricode={edgeTeam.tricode} logoUrl={edgeTeam.logoUrl} points={game.edge.points} />
              {/* the ring follows the chip wherever the footer wraps it */}
              {coachsPick && <span className="bd-note-ring" aria-hidden="true" style={{ inset: "-9px -12px" }} />}
            </span>
          )}
        </div>
      )}

      {coachsPick && <span className="bd-note-tag">coach's pick</span>}
    </article>
  );
};
