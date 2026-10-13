import type { FC } from "react";
import type { TeamLookup } from "../../types/teams";
import { teamOf } from "../../utils/playerStats";

/** The team's logo beside its tricode: the logo is the identity, the tricode the label in a tight spot. */
export const TeamChip: FC<{ tricode: string; teams: TeamLookup }> = ({ tricode, teams }) => {
  const team = teamOf(teams, tricode);
  return (
    <span className="lb-team" title={team.name}>
      <img src={team.logoUrl} alt={team.name === tricode ? "" : team.name} />
      {tricode}
    </span>
  );
};
