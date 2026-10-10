import type { PlayerPropData } from "../../types/player";
import type { StatDef } from "../../utils/playerStats";

/** What a player page hands its tabs: the data, and the stat picked for the last-five chart (which the season
 *  tables highlight too, so it lives above the tabs). */
export interface PlayerPageContext<D, G> {
  data: D;
  stat: StatDef<G>;
  setStat: (key: string) => void;
}

export type PropsContext = { data: { props: PlayerPropData[] } };
