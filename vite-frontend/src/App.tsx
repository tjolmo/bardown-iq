import { Routes, Route, Navigate } from "react-router-dom";

import SkaterDashboard from "./pages/SkaterDashboard";
import GoalieDashboard from "./pages/GoalieDashboard";
import { SkaterLastFive, SkaterNextGame, SkaterSeason } from "./components/skater/SkaterPanels";
import { GoalieLastFive, GoalieNextGame, GoalieSeason } from "./components/goalie/GoaliePanels";
import { PlayerPropsPanel } from "./components/player/PlayerPropsPanel";
import TeamSchedulePage from "./pages/TeamSchedulePage";
import RosterPage from "./pages/RosterPage";
import DailySchedulePage from "./pages/DailySchedulePage";
import TeamsPage from "./pages/TeamsPage";
import SearchResultsPage from "./pages/SearchResultsPage";
import TopPlayersPage from "./pages/TopPlayersPage";
import EdgePlayersPage from "./pages/EdgePlayersPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/schedule/today" />} />

      {/* the tabs switch with history replace (PlayerTabs), so Back leaves the player page in one step */}
      <Route path="/player/:id" element={<SkaterDashboard />}>
        <Route index element={<Navigate to="predictions" replace />} />
        <Route path="predictions" element={<SkaterNextGame />} />
        <Route path="props" element={<PlayerPropsPanel />} />
        <Route path="recent" element={<SkaterLastFive />} />
        <Route path="season" element={<SkaterSeason />} />
      </Route>

      <Route path="/goalie/:id" element={<GoalieDashboard />}>
        <Route index element={<Navigate to="predictions" replace />} />
        <Route path="predictions" element={<GoalieNextGame />} />
        <Route path="props" element={<PlayerPropsPanel />} />
        <Route path="recent" element={<GoalieLastFive />} />
        <Route path="season" element={<GoalieSeason />} />
      </Route>

      <Route path="/schedule/team/:tricode" element={<TeamSchedulePage />} />
      <Route path="/schedule/:date" element={<DailySchedulePage />} />
      <Route path="/roster/:tricode" element={<RosterPage />} />
      <Route path="/teams" element={<TeamsPage />} />
      <Route path="/search" element={<SearchResultsPage />} />
      <Route path="/top-players/:player_type/:season/:n" element={<TopPlayersPage />} />
      <Route path="/edges" element={<EdgePlayersPage />} />
    </Routes>
  );
}