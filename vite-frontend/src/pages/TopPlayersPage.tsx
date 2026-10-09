import type { FC } from "react";
import { useTopPlayers } from "../hooks/useTopPlayers";
import { PlayerCard } from "../components/roster/PlayerCard";
import LoadingPage from "./LoadingPage";
import ErrorPage from "./ErrorPage";
import { useParams } from "react-router-dom";

export const TopPlayersPage: FC = () => {
  const { season, n, player_type } = useParams<{ season: string; n: string; player_type: "skaters" | "goalies" }>();
  const { data: players, loading, error } = useTopPlayers(season!, Number(n), player_type!);

  if (error) return <ErrorPage message="Error loading top players." />;
  if (loading) return <LoadingPage />;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50/30 to-slate-100 font-sans p-4 sm:p-6 lg:p-10">
      <div className="fixed top-0 right-0 w-96 h-96 bg-blue-400/10 rounded-full blur-3xl pointer-events-none" />
      <div className="fixed bottom-0 left-0 w-64 h-64 bg-indigo-400/10 rounded-full blur-3xl pointer-events-none" />

      <div className="relative max-w-5xl mx-auto space-y-6">
        <div className="bg-white rounded-3xl shadow-xl shadow-slate-200/60 overflow-hidden">
          <div className="h-20 bg-gradient-to-r from-blue-700 via-blue-600 to-indigo-700 relative">
            <div
              className="absolute inset-0 opacity-20"
              style={{
                backgroundImage:
                  "repeating-linear-gradient(45deg, transparent, transparent 10px, rgba(255,255,255,.15) 10px, rgba(255,255,255,.15) 11px)",
              }}
            />
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <h1 className="text-white font-black text-2xl tracking-tight drop-shadow">
                Top {player_type === "skaters" ? "Skaters" : "Goalies"}
              </h1>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
          {(players ?? []).map((player, index) => (
            <PlayerCard key={player.id} player={player} index={index} />
          ))}
        </div>
      </div>
    </div>
  );
};

export default TopPlayersPage;
