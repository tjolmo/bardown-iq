import type { FC } from "react";
import { NavLink } from "react-router-dom";

export interface PlayerTab {
  to: string;     // the child route: "predictions", "props", "recent", "season"
  num: string;    // the headline number on the card
  label: string;
  sub: string;
}

/** One card per view. Switching replaces the history entry instead of adding one, so Back leaves the player page
 *  in a single step however many tabs were opened. */
export const PlayerTabs: FC<{ tabs: PlayerTab[] }> = ({ tabs }) => (
  <nav className="pl-maintabs" aria-label="Player views">
    {tabs.map((t) => (
      <NavLink key={t.to} to={t.to} replace className="pl-maintab">
        <span className="pl-maintab-num">{t.num}</span>
        <span className="pl-maintab-text">
          <span className="pl-maintab-label">{t.label}</span>
          <span className="pl-maintab-sub">{t.sub}</span>
        </span>
      </NavLink>
    ))}
  </nav>
);
