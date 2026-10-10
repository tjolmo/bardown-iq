import type { FC } from "react";
import { Link } from "react-router-dom";
import type { PlayerData, UpcomingGame } from "../../types/player";
import type { TeamLookup } from "../../types/teams";
import { localTime, shortDay, splitTeamName } from "../../utils/gameStatus";
import { POSITION_NAMES, teamOf } from "../../utils/playerStats";

interface PlayerHeroProps {
  player: PlayerData;
  teams: TeamLookup;
  upcomingGame: UpcomingGame | null;
  // this season's line under the name: [{ label: "GP", value: "30" }, …]
  seasonLine: { label: string; value: string }[];
}

/** The page opener: the player on the left, the headshot at centre ice, the next game on the right. */
export const PlayerHero: FC<PlayerHeroProps> = ({ player, teams, upcomingGame, seasonLine }) => {
  const team = player.team !== "N/A" ? teamOf(teams, player.team) : null;
  const [first, ...rest] = player.name.split(" ");
  const opp = upcomingGame?.opposing_team_tricode ? teamOf(teams, upcomingGame.opposing_team_tricode) : null;

  return (
    <section className="bd-rink" aria-labelledby="player-name">
      <div className="bd-rink-marks" aria-hidden="true">
        <i className="bd-rink-goal-l" />
        <i className="bd-rink-goal-r" />
        <i className="bd-rink-blue-l" />
        <i className="bd-rink-blue-r" />
        <i className="bd-rink-center" />
        <i className="bd-rink-crease-l" />
        <i className="bd-rink-crease-r" />
      </div>
      <div className="pl-hero-grid">
        <div className="bd-rink-zone">
          <div className="pl-meta">
            {team && <img src={team.logoUrl} alt={team.name} />}
            {player.number !== null && <span className="pl-num">#{player.number}</span>}
            <span>{POSITION_NAMES[player.position] ?? player.position}</span>
            {team && (
              <>
                <span aria-hidden="true">·</span>
                <Link to={`/roster/${team.tricode}`}>{splitTeamName(team.name).nickname}</Link>
              </>
            )}
          </div>
          <h1 className="bd-display-xl" id="player-name">
            {first}
            {rest.length > 0 && (
              <>
                <br />
                {rest.join(" ")}
              </>
            )}
          </h1>
          <div className="pl-season" aria-label="This season">
            {seasonLine.map((s) => (
              <div key={s.label}>
                <span className="bd-score">{s.value}</span>
                <span className="bd-label">{s.label}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="pl-face">
          {player.headshotUrl ? (
            <img src={player.headshotUrl} alt={`${player.name} headshot`} />
          ) : (
            <svg viewBox="0 0 200 200" role="img" aria-label={`No headshot for ${player.name}`}>
              <circle cx="100" cy="82" r="38" fill="var(--ink-subtle)" />
              <path d="M30 200c6-44 36-68 70-68s64 24 70 68z" fill="var(--ink-subtle)" />
            </svg>
          )}
        </div>

        <div className="bd-rink-zone pl-zone-right">
          <span className="bd-label">Next game</span>
          {upcomingGame && opp ? (
            <>
              <Link to={`/roster/${opp.tricode}`} className="pl-next-opp">
                <span className="pl-vs">{upcomingGame.home_away === "AWAY" ? "@" : "vs"}</span>
                <img src={opp.logoUrl} alt={opp.name} />
              </Link>
              <div className="bd-team-name">{splitTeamName(opp.name).nickname}</div>
              {upcomingGame.time && (
                <div className="bd-row" style={{ gap: 8, justifyContent: "flex-end" }}>
                  <span className="bd-chip bd-chip-quiet">{shortDay(upcomingGame.time)}</span>
                  <span className="bd-chip bd-chip-time">{localTime(upcomingGame.time)}</span>
                </div>
              )}
              {upcomingGame.venue && <span className="bd-team-city">{upcomingGame.venue}</span>}
            </>
          ) : (
            <div className="bd-team-name">None scheduled</div>
          )}
        </div>
      </div>
    </section>
  );
};
