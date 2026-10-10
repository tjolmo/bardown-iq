import type { FC } from "react";
import { Link } from "react-router-dom";
import type { LineupPlayer } from "../../types/lineup";
import { lastName, playerLink } from "../../utils/lineup";

/** One player on the board: sweater-number disc, slot (with DTD / IN flags), last name. */
export const LineupPlayerLink: FC<{ player: LineupPlayer; slot?: string | null; incoming?: boolean; large?: boolean }> = ({
  player, slot, incoming = false, large = false,
}) => {
  const flags = [incoming ? "IN" : null, player.injuryStatus === "day_to_day" ? "DTD" : null].filter(Boolean);
  const name = [player.firstName, player.lastName].filter(Boolean).join(" ");
  return (
    <Link to={playerLink(player)} className={`rs-player${incoming ? " rs-player-in" : ""}`}
      aria-label={`${name}${player.number !== null ? `, number ${player.number}` : ""}${slot ? `, ${slot}` : ""}`}>
      <span className={`rs-disc${large ? " rs-disc-lg" : ""}`} aria-hidden="true">{player.number ?? "–"}</span>
      <span className="rs-player-text" aria-hidden="true">
        <span className="rs-slot">
          {slot ?? player.slot}
          {flags.length > 0 && <> · <b>{flags.join(" · ")}</b></>}
        </span>
        <span className={`rs-name${large ? " rs-name-lg" : ""}`}>{lastName(player)}</span>
      </span>
    </Link>
  );
};
