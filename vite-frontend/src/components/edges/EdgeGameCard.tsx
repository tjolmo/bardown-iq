import type { FC } from "react";
import { Link } from "react-router-dom";
import type { TeamLookup } from "../../types/teams";
import { formatBook, formatPrice, type OddsFormat } from "../../utils/books";
import type { PricedPlayer, PricedProp } from "../../utils/edgePricing";
import { localTime, splitTeamName } from "../../utils/gameStatus";
import { impliedProb, pct, teamOf } from "../../utils/playerStats";
import { formatPropType } from "../../utils/propMarkets";
import { Headshot } from "../rinkboard/Headshot";
import { edgeChipClass, edgeText, fullName, isYes, playerPath, SHORT_MARKETS, SHORT_POSITION, sideName } from "./edgeFormat";

export interface EdgeRow {
  player: PricedPlayer;
  edgeProps: PricedProp[];
}

interface Props {
  rows: EdgeRow[];              // one game's players, best edge first
  teams: TeamLookup;
  format: OddsFormat;
}

const nickname = (teams: TeamLookup, tricode: string): string => {
  const team = teamOf(teams, tricode);
  return team.name === tricode ? tricode : splitTeamName(team.name).nickname;
};

/** One game: the matchup across the top, each team's players down its own side of the red line, a line per bet. */
export const EdgeGameCard: FC<Props> = ({ rows, teams, format }) => {
  const first = rows[0].player;
  const home = first.home ? first.team ?? "" : first.opponent;
  const away = first.home ? first.opponent : first.team ?? "";
  const best = Math.max(...rows.map((r) => r.edgeProps[0].edge!));

  const side = (tricode: string, cls: string) => {
    const players = rows.filter((r) => r.player.team === tricode);
    return (
      <div className={`ed-game-col ${cls}`}>
        {players.length === 0 ? (
          <p className="ed-game-empty">No {nickname(teams, tricode)} side passes these filters.</p>
        ) : players.map(({ player, edgeProps }) => (
          <div className="ed-gp" key={player.player_id}>
            <Headshot player={player} size={44} />
            <div className="ed-who">
              <Link to={playerPath(player)} className="lb-name">{fullName(player)}</Link>
              <span className="lb-chips">
                {player.position && <span className="lb-chip">{SHORT_POSITION[player.position] ?? player.position}</span>}
              </span>
            </div>
            <div className="ed-gp-bets">
              {edgeProps.map((p) => (
                <div className="ed-gp-bet" key={`${p.prop_type}-${p.over_under}-${p.line}`}>
                  <span>{sideName(p.over_under)} {!isYes(p.over_under) && p.line} {SHORT_MARKETS[p.prop_type] ?? formatPropType(p.prop_type)}</span>
                  <em>
                    {formatPrice(p.odds, format)} {formatBook(p.book)}
                    {p.model_prob !== null && ` · ${pct(p.model_prob)} vs ${pct(impliedProb(p.odds))}`}
                  </em>
                  <span className={edgeChipClass(p.edge)}>{edgeText(p.edge!)}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  };

  return (
    <article className="bd-card ed-game">
      <div className="ed-game-head">
        <div className="ed-game-team">
          <img src={teamOf(teams, away).logoUrl} alt="" />
          <div><span className="bd-label">Away</span><div className="bd-team-name">{nickname(teams, away)}</div></div>
        </div>
        <div className="ed-game-mid">
          {first.start_time && <span className="bd-chip bd-chip-time">{localTime(first.start_time)}</span>}
          <span className="bd-label">{rows.length} {rows.length === 1 ? "player" : "players"} · best {edgeText(best)}</span>
        </div>
        <div className="ed-game-team ed-game-home">
          <div><span className="bd-label">Home</span><div className="bd-team-name">{nickname(teams, home)}</div></div>
          <img src={teamOf(teams, home).logoUrl} alt="" />
        </div>
      </div>
      <div className="ed-game-cols">
        {side(away, "ed-away")}
        {side(home, "ed-home")}
      </div>
    </article>
  );
};
