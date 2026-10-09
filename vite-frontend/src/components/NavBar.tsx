import { Link, useLocation } from "react-router-dom";
import SearchBar from "./SearchBar";

const TABS = [
  { to: "/schedule/today", label: "Tonight" },
  { to: "/teams", label: "Teams" },
  { to: "/top-players/skaters/current/50", label: "Top Skaters" },
  { to: "/top-players/goalies/current/30", label: "Top Goalies" },
  { to: "/edges", label: "Edges" },
];

// any day's board counts as "Tonight" in the nav; a team's schedule doesn't
const isBoard = (path: string) => path.startsWith("/schedule/") && !path.startsWith("/schedule/team/");

// a team's schedule sits under Teams
const isCurrent = (to: string, path: string) =>
  to === "/schedule/today"
    ? isBoard(path)
    : to === "/teams"
      ? path.startsWith("/teams") || path.startsWith("/schedule/team/")
      : path.startsWith(to);

export default function Navbar() {
  const { pathname } = useLocation();

  return (
    <header className="bd-nav">
      <div className="bd-nav-inner">
        <Link to="/schedule/today" className="bd-wordmark" aria-label="BarDown IQ home">
          BarDown <span className="bd-wordmark-iq">IQ</span>
        </Link>
        <nav className="bd-nav-links" aria-label="Main">
          {TABS.map((tab) => (
            <Link
              key={tab.to}
              to={tab.to}
              className="bd-nav-link"
              aria-current={isCurrent(tab.to, pathname) ? "page" : undefined}
            >
              {tab.label}
            </Link>
          ))}
        </nav>
        <SearchBar />
      </div>
    </header>
  );
}
