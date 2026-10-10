import type { FC } from "react";
import { Link } from "react-router-dom";
import type { LineupPlayer, TeamLineup } from "../../types/lineup";
import { lastName, lineupNote, playerLink } from "../../utils/lineup";

const POSITION_SHORT: Record<string, string> = { C: "C", L: "LW", R: "RW", D: "D", G: "G" };

const who = (p: LineupPlayer) => [p.number !== null ? `#${p.number}` : null, p.position ? POSITION_SHORT[p.position] ?? p.position : null]
  .filter(Boolean).join(" ");

/** Who comes in and who goes out against the last game's lineup, with why when it's known. */
export const LineupChanges: FC<{ lineup: TeamLineup }> = ({ lineup }) => {
  const { playersIn, playersOut } = lineup.changes;
  if (playersIn.length === 0 && playersOut.length === 0) return null;
  const injuryOf = new Map(lineup.injuries.filter((i) => i.playerId !== null).map((i) => [i.playerId!, i]));
  const note = lineupNote(lineup);

  const whyIn = (p: LineupPlayer) =>
    p.gamesScratched ? `back after ${p.gamesScratched} ${p.gamesScratched === 1 ? "game" : "games"} as a scratch` : "into the lineup";
  const whyOut = (p: LineupPlayer) => {
    const injury = injuryOf.get(p.id);
    if (!injury) return "not on the roster";
    const status = injury.status === "day_to_day" ? "day-to-day" : injury.status === "ltir" ? "LTIR" : injury.status === "ir" ? "IR" : injury.status;
    return [status, injury.injuryType?.toLowerCase()].filter(Boolean).join(", ");
  };

  return (
    <div className="rs-changes">
      <span className="bd-label">Since last game</span>
      {playersIn.map((p) => (
        <Link key={`in-${p.id}`} to={playerLink(p)} className="rs-change">
          <span className="rs-change-tag rs-change-in">IN</span>
          <span><span className="rs-name">{lastName(p)}</span> <small>{who(p)} · {whyIn(p)}</small></span>
        </Link>
      ))}
      {playersOut.map((p) => (
        <Link key={`out-${p.id}`} to={playerLink(p)} className="rs-change">
          <span className="rs-change-tag rs-change-out">OUT</span>
          <span><span className="rs-name">{lastName(p)}</span> <small>{who(p)} · {whyOut(p)}</small></span>
        </Link>
      ))}
      {note && <span className="bd-note-tag" aria-hidden="true">{note}</span>}
    </div>
  );
};
