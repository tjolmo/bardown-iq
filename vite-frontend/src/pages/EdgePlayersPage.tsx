import { useMemo, useState, type FC } from "react";
import { Link } from "react-router-dom";
import { useEdgeBoard } from "../hooks/useEdgeBoard";
import { PlayerPropCard, formatPropType } from "../components/player/PlayerPropCard";
import type { EdgePlayer } from "../types/edges";
import type { PlayerPropData } from "../types/player";
import ErrorPage from "./ErrorPage";

const MIN_EDGES = [
  { value: 0, label: "Any edge" },
  { value: 0.03, label: "3%+" },
  { value: 0.05, label: "5%+" },
  { value: 0.1, label: "10%+" },
];

// American odds at or above this are long shots (anytime goals for depth players, mostly)
const LONG_SHOT_ODDS = 400;

const formatEdge = (edge: number): string => `${edge > 0 ? "+" : ""}${(edge * 100).toFixed(1)}%`;

const formatGameDate = (date: number): string => {
  const s = String(date);
  return new Date(`${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}T12:00:00`).toLocaleDateString(undefined, {
    weekday: "long", month: "long", day: "numeric",
  });
};

const formatStart = (iso: string | null): string =>
  iso ? new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }) : "";

const Chip: FC<{ active: boolean; onClick: () => void; children: React.ReactNode }> = ({ active, onClick, children }) => (
  <button
    type="button"
    onClick={onClick}
    aria-pressed={active}
    className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all ${active
      ? "bg-blue-600 text-white shadow-md shadow-blue-200"
      : "bg-white text-slate-500 hover:text-slate-700 shadow-sm shadow-slate-200/60"
      }`}
  >
    {children}
  </button>
);

interface RowProps {
  player: EdgePlayer;
  edgeProps: PlayerPropData[];
}

const EdgePlayerRow: FC<RowProps> = ({ player, edgeProps }) => {
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? player.props : edgeProps;
  const best = Math.max(...edgeProps.map((p) => p.edge ?? 0));
  const linkTo = player.position === "G" ? `/goalie/${player.player_id}` : `/player/${player.player_id}`;

  return (
    <div className="bg-white/60 rounded-3xl shadow-lg shadow-slate-200/50 p-4 sm:p-5">
      <div className="flex items-center gap-3 mb-4">
        {player.headshot ? (
          <img src={player.headshot} alt="" className="w-12 h-12 rounded-full bg-slate-100 object-cover shrink-0" />
        ) : (
          <div className="w-12 h-12 rounded-full bg-slate-100 shrink-0" />
        )}
        <div className="min-w-0 flex-1">
          <Link to={linkTo} className="font-black text-slate-800 hover:text-blue-700 truncate block">
            {player.first_name} {player.last_name}
          </Link>
          <div className="text-xs text-slate-500 flex flex-wrap items-center gap-x-2">
            <span className="font-semibold">{player.position}</span>
            <span>
              {player.team} {player.home ? "vs" : "@"} {player.opponent}
            </span>
            <span>{formatStart(player.start_time)}</span>
            {player.starter_status && (
              <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                {player.starter_status} starter
              </span>
            )}
          </div>
        </div>
        <span className="shrink-0 inline-flex items-center rounded-lg bg-emerald-50 px-3 py-1.5 text-sm font-bold text-emerald-700 tabular-nums">
          {formatEdge(best)}
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {shown.map((prop) => (
          <PlayerPropCard key={`${prop.prop_type}-${prop.over_under}-${prop.line}-${prop.source}`} {...prop} />
        ))}
      </div>

      {player.props.length > edgeProps.length && (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="mt-3 text-xs font-semibold text-blue-600 hover:text-blue-700"
        >
          {showAll ? "Show edges only" : `Show all ${player.props.length} props`}
        </button>
      )}
    </div>
  );
};

export const EdgePlayersPage: FC = () => {
  const { data: board, loading, error } = useEdgeBoard();
  const [minEdge, setMinEdge] = useState(0);
  const [market, setMarket] = useState<string | null>(null);
  const [hideLongShots, setHideLongShots] = useState(false);

  const markets = useMemo(() => {
    const keys = new Set<string>();
    board?.players.forEach((p) => p.props.forEach((prop) => (prop.edge ?? 0) > 0 && keys.add(prop.prop_type)));
    return [...keys].sort((a, b) => formatPropType(a).localeCompare(formatPropType(b)));
  }, [board]);

  const rows = useMemo(() => {
    const qualifies = (prop: PlayerPropData) =>
      prop.edge !== null && prop.edge > minEdge
      && (market === null || prop.prop_type === market)
      && !(hideLongShots && prop.odds >= LONG_SHOT_ODDS);
    return (board?.players ?? [])
      .map((player) => ({ player, edgeProps: player.props.filter(qualifies) }))
      .filter((row) => row.edgeProps.length > 0)
      .sort((a, b) => Math.max(...b.edgeProps.map((p) => p.edge!)) - Math.max(...a.edgeProps.map((p) => p.edge!)));
  }, [board, minEdge, market, hideLongShots]);

  if (error) return <ErrorPage message="Error loading players with edge." />;

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
              <h1 className="text-white font-black text-2xl tracking-tight drop-shadow">Players with Edge</h1>
              {board?.game_date && (
                <p className="text-blue-200 text-xs font-semibold mt-0.5 tracking-widest uppercase">
                  {formatGameDate(board.game_date)}
                </p>
              )}
            </div>
          </div>
          <p className="px-5 py-3 text-xs text-slate-500">
            Players with at least one prop where the model's chance times the best available price is above 1.
            Edge is the expected return per unit staked. Best prices are taken across books, so small edges are mostly
            line shopping, not a forecast.
          </p>
        </div>

        {loading ? (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <div className="relative w-12 h-12">
              <div className="absolute inset-0 rounded-full border-4 border-slate-100" />
              <div className="absolute inset-0 rounded-full border-4 border-transparent border-t-blue-600 animate-spin" />
            </div>
            <p className="text-slate-700 font-semibold text-sm">Pricing the slate's props…</p>
            <p className="text-slate-400 text-xs">The first load of the day can take up to a minute.</p>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              {MIN_EDGES.map((m) => (
                <Chip key={m.value} active={minEdge === m.value} onClick={() => setMinEdge(m.value)}>{m.label}</Chip>
              ))}
              <span className="w-px h-6 bg-slate-200 mx-1" />
              <Chip active={market === null} onClick={() => setMarket(null)}>All markets</Chip>
              {markets.map((m) => (
                <Chip key={m} active={market === m} onClick={() => setMarket(m)}>{formatPropType(m)}</Chip>
              ))}
              <span className="w-px h-6 bg-slate-200 mx-1" />
              <Chip active={hideLongShots} onClick={() => setHideLongShots((v) => !v)}>
                Hide +{LONG_SHOT_ODDS} and longer
              </Chip>
            </div>

            <p className="text-xs text-slate-500">
              {rows.length} of {board?.players_priced ?? 0} priced players
              {board?.refreshing && " · refreshing prices in the background"}
            </p>

            {rows.length === 0 ? (
              <div className="bg-white rounded-3xl shadow-lg shadow-slate-200/50 p-10 text-center text-sm text-slate-500">
                {board?.game_date ? "No props match these filters." : "No upcoming games with props yet."}
              </div>
            ) : (
              <div className="space-y-4">
                {rows.map(({ player, edgeProps }) => (
                  <EdgePlayerRow key={player.player_id} player={player} edgeProps={edgeProps} />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default EdgePlayersPage;
