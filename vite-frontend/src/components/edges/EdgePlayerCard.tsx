import { useState, type FC } from "react";
import { Link } from "react-router-dom";
import type { TeamLookup } from "../../types/teams";
import type { OddsFormat } from "../../utils/books";
import { formatPrice } from "../../utils/books";
import type { PricedPlayer, PricedProp } from "../../utils/edgePricing";
import { localTime } from "../../utils/gameStatus";
import { Headshot } from "../rinkboard/Headshot";
import { TeamChip } from "../rinkboard/TeamChip";
import { EdgePropRow } from "./EdgePropRow";
import { edgeText, fullName, playerPath, SHORT_POSITION } from "./edgeFormat";

interface Props {
  player: PricedPlayer;
  edgeProps: PricedProp[];       // the sides that pass the filters, best edge first
  rank: number;
  teams: TeamLookup;
  format: OddsFormat;
  myBooks: ReadonlySet<string>;
  longShot: number;              // American odds at or above this get the coach's note
}

const propKey = (p: PricedProp) => `${p.prop_type}-${p.over_under}-${p.line}-${p.source}`;

/** One player on the board: who, the game, the best edge, then a row per side that passes the filters; the rest of
 *  his priced sides come in quieter on demand. */
export const EdgePlayerCard: FC<Props> = ({ player, edgeProps, rank, teams, format, myBooks, longShot }) => {
  const [showAll, setShowAll] = useState(false);
  const rest = player.props
    .filter((p) => !edgeProps.includes(p))
    .sort((a, b) => (b.edge ?? -Infinity) - (a.edge ?? -Infinity));
  const long = edgeProps.find((p) => p.odds >= longShot);

  return (
    <article className="bd-card ed-card">
      {long && <span className="bd-note-tag">{formatPrice(long.odds, format)} long shot</span>}
      <div className="ed-head">
        <span className="ed-rank">{rank}</span>
        <Headshot player={player} size={60} />
        <div className="ed-who">
          <Link to={playerPath(player)} className="lb-name">{fullName(player)}</Link>
          <span className="lb-chips">
            {player.team && <TeamChip tricode={player.team} teams={teams} />}
            {player.position && <span className="lb-chip">{SHORT_POSITION[player.position] ?? player.position}</span>}
            <span className="lb-chip">
              {player.home ? "vs" : "@"} {player.opponent}
              {player.start_time && ` · ${localTime(player.start_time)}`}
            </span>
            {player.starter_status && <span className="lb-chip">{player.starter_status} starter</span>}
          </span>
        </div>
        <div className="ed-best">
          <span className="bd-score">{edgeText(edgeProps[0].edge!)}</span>
          <span className="bd-label">{edgeProps.length > 1 ? `Best of ${edgeProps.length} edges` : "Edge"}</span>
        </div>
      </div>
      <ul className="pl-props ed-props">
        <li className="pl-prop pl-prop-head" aria-hidden="true">
          <span className="bd-label">Market</span>
          <span className="bd-label">Side</span>
          <span className="bd-label">Best price</span>
          <span className="bd-label">Model vs book</span>
          <span className="bd-label">Edge</span>
        </li>
        {edgeProps.map((p) => <EdgePropRow key={propKey(p)} prop={p} format={format} myBooks={myBooks} />)}
        {showAll && rest.map((p) => <EdgePropRow key={propKey(p)} prop={p} format={format} myBooks={myBooks} quiet />)}
      </ul>
      {rest.length > 0 && (
        <div className="ed-foot">
          <span>
            {showAll
              ? `${rest.length} more ${rest.length === 1 ? "side" : "sides"} for ${player.first_name}, none passing these filters`
              : `${player.props.length} sides priced for ${player.first_name}`}
          </span>
          <button type="button" className="pl-books" aria-expanded={showAll} onClick={() => setShowAll(!showAll)}>
            {showAll ? "Edges only" : `Show all ${player.props.length}`}
          </button>
        </div>
      )}
    </article>
  );
};
