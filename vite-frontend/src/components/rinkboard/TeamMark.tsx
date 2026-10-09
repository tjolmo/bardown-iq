import type { FC } from "react";
import { Link } from "react-router-dom";
import type { Team } from "../../types/teams";
import { splitTeamName } from "../../utils/gameStatus";

interface TeamMarkProps {
  team: Team;
  home?: boolean;
}

/** A team's logo over its city and nickname; links to the team's schedule. */
export const TeamMark: FC<TeamMarkProps> = ({ team, home = false }) => {
  const { city, nickname } = splitTeamName(team.name);
  return (
    <Link to={`/schedule/team/${team.tricode}`} className={`bd-team${home ? " bd-team-home" : ""}`}>
      <img className="bd-team-logo" src={team.logoUrl} alt={team.name} />
      <div>
        {city && <div className="bd-team-city">{city}</div>}
        <div className="bd-team-name">{nickname}</div>
      </div>
    </Link>
  );
};
