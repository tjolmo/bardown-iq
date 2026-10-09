import { useState, type FC } from "react";
import type { PlayerPropData } from "../../types/player";
import { formatBook, formatOdds } from "../../utils/books";

export const formatPropType = (prop_type: string): string => {
    const map: Record<string, string> = {
        "player_goals": "Goals",
        "player_assists": "Assists",
        "player_points": "Points",
        "player_total_saves": "Saves",
        "player_shots_on_goal": "Shots on Goal",
        "player_blocked_shots": "Blocked Shots",
        "player_hits": "Hits",
        "player_power_play_points": "Power Play Points",
        "player_goal_scorer_anytime": "Anytime Goal",
    };
    return map[prop_type] || prop_type;
}

const formatEdge = (edge: number): string =>
    `${edge > 0 ? "+" : ""}${(edge * 100).toFixed(1)}%`;

export const PlayerPropCard: FC<PlayerPropData> = ({ over_under, line, odds, prop_type, model_prob, edge, source, book, other_books }) => {
    const [showBooks, setShowBooks] = useState(false);
    const otherBooks = other_books ?? [];
    const side = over_under.toUpperCase();
    const isOver = side !== "UNDER";   // "Yes" (anytime goal) reads like an over

    const directionClasses = isOver
        ? "bg-emerald-50 text-emerald-700"
        : "bg-rose-50 text-rose-700";

    // a positive expected return at this price is the model's edge over the book
    const edgeClasses = edge !== null && edge > 0
        ? "text-emerald-600"
        : "text-slate-400";

    return (
        <div className="relative overflow-hidden rounded-2xl bg-white shadow-lg shadow-slate-200/50 hover:shadow-xl hover:-translate-y-0.5 transition p-5">
            <div className="flex items-center justify-between gap-2 mb-3">
                <span className="text-xs font-semibold tracking-widest uppercase text-slate-400">
                    {formatPropType(prop_type)}
                </span>
                {source === "espn" ? (
                    <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-400" title="Price from ESPN's feed">
                        {book ?? "ESPN"}
                    </span>
                ) : book && (
                    <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-400" title="Best price across books at the consensus line">
                        {formatBook(book)}
                    </span>
                )}
            </div>

            <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-2 min-w-0">
                    <span
                        className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${directionClasses}`}
                    >
                        <span aria-hidden="true">{isOver ? "▲" : "▼"}</span>
                        {side === "YES" ? "YES" : isOver ? "OVER" : "UNDER"}
                    </span>
                    {side !== "YES" && (
                        <span className="text-2xl font-black text-slate-800 leading-none">
                            {line}
                        </span>
                    )}
                </div>

                <span className="inline-flex items-center rounded-lg bg-blue-50 px-3 py-1.5 text-sm font-bold text-blue-700 tabular-nums">
                    {formatOdds(odds)}
                </span>
            </div>

            {model_prob !== null && (
                <div className="mt-3 flex items-center justify-between text-xs tabular-nums">
                    <span className="text-slate-500">Model {(model_prob * 100).toFixed(0)}%</span>
                    {edge !== null && (
                        <span className={`font-semibold ${edgeClasses}`}>Edge {formatEdge(edge)}</span>
                    )}
                </div>
            )}

            {otherBooks.length > 0 && (
                <div className="mt-3 border-t border-slate-100 pt-2">
                    <button
                        type="button"
                        onClick={() => setShowBooks((v) => !v)}
                        aria-expanded={showBooks}
                        className="text-[11px] font-semibold text-blue-600 hover:text-blue-700"
                    >
                        {showBooks ? "Hide books" : `+${otherBooks.length} book${otherBooks.length === 1 ? "" : "s"}`}
                    </button>
                    {showBooks && (
                        <ul className="mt-2 space-y-1 text-xs tabular-nums">
                            {otherBooks.map((b) => (
                                <li key={`${b.book}-${b.line}`} className="flex items-center justify-between gap-2">
                                    <span className={b.consensus ? "text-slate-600" : "text-slate-400"}
                                          title={b.consensus ? undefined : "Not part of the consensus price"}>
                                        {formatBook(b.book)}
                                        {b.line !== line && side !== "YES" && (
                                            <span className="text-slate-400"> · {b.line}</span>
                                        )}
                                    </span>
                                    <span className="font-semibold text-slate-700">{formatOdds(b.odds)}</span>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            )}
        </div>
    );
};
