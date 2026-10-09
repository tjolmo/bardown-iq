import { NavLink } from "react-router-dom";
import SearchBar from "./SearchBar";

const TABS = [
  { to: "/schedule/today", label: "Today's Games", icon: "📅" },
  { to: "/teams", label: "Teams", icon: "🏒" },
  { to: "/top-players/skaters/current/50", label: "Top Skaters", icon: "🏒" },
  { to: "/top-players/goalies/current/30", label: "Top Goalies", icon: "🧤" },
  { to: "/edges", label: "Players with Edge", icon: "📈" },
];

export default function Navbar() {
  return (
    <nav className="sticky top-0 z-50 bg-white/80 backdrop-blur-md border-b border-slate-100 shadow-sm shadow-slate-200/50">
      <div className="max-w-5xl mx-auto px-4 flex items-center gap-1 h-14 overflow-x-auto">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            className={({ isActive }) =>
              `flex shrink-0 items-center gap-1.5 whitespace-nowrap px-3 py-2 rounded-xl text-sm font-bold transition-all ${isActive
                ? "bg-blue-600 text-white shadow-md shadow-blue-200"
                : "text-slate-400 hover:text-slate-600 hover:bg-slate-50"
              }`
            }
          >
            <span>{tab.icon}</span>
            <span>{tab.label}</span>
          </NavLink>
        ))}
        <SearchBar />
      </div>
    </nav>
  );
}