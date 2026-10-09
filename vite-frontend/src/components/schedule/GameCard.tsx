import type { FC } from "react";
import type { TeamScheduledGame } from "../../types/teams";
import { TeamCard } from "./TeamCard";
import { formatBook, formatOdds } from "../../utils/books";

interface GameCardProps {
  game: TeamScheduledGame;
  index: number;
}

export const GameCard: FC<GameCardProps> = ({ game, index }) => {
  const scoresExist = game.awayScore !== null && game.homeScore !== null;

  return (
    <div
      className={`relative overflow-hidden rounded-2xl bg-white shadow-lg shadow-slate-200/50 transition-all duration-300 hover:shadow-xl hover:shadow-blue-100/60 hover:-translate-y-0.5 ${game.isNextGame ? "ring-2 ring-blue-500 ring-offset-2" : ""
        }`}
      style={{ animationDelay: `${index * 80}ms` }}
    >
      {game.isNextGame && (
        <div className="absolute top-0 left-1/2 -translate-x-1/2 z-10">
          <span className="inline-block bg-blue-600 text-white text-[10px] font-black tracking-widest uppercase px-3 py-0.5 rounded-b-lg shadow-md shadow-blue-300/50">
            Next Game
          </span>
        </div>
      )}
      <div
        className="absolute inset-0 opacity-[0.025]"
        style={{
          backgroundImage:
            "repeating-linear-gradient(45deg, #1e40af, #1e40af 1px, transparent 1px, transparent 12px)",
        }}
      />

      <div className="relative flex flex-col sm:flex-row items-center sm:items-stretch gap-4 p-5 sm:p-6">
        <TeamCard team={game.awayTeam} type="Away" />

        <div className="flex-1 flex flex-col items-center justify-center gap-3 py-1 order-first sm:order-none">
          <div className="flex items-center gap-2 flex-wrap justify-center">
            <span className="text-xs font-bold text-slate-600 bg-blue-50 px-3 py-1 rounded-xl">
              {game.date}
            </span>
            <span className="text-xs font-bold text-blue-600">
              {new Date(game.time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          </div>

          <div className="flex items-center gap-2 sm:gap-3">
            <div className="flex flex-col items-center">
              {scoresExist ? (
                <span className="text-3xl sm:text-4xl font-black text-slate-800 tabular-nums">
                  {game.awayScore}
                </span>
              ) : game.predictions && game.predictions.away.prob_win !== null && (
                <>
                  <span className="text-3xl sm:text-4xl font-black text-slate-800 tabular-nums">
                    {(game.predictions.away.prob_win * 100).toFixed(0)}%
                  </span>
                  <span className="text-[11px] font-bold text-blue-500 mt-0.5 tabular-nums">
                    {game.moneyline?.away}
                  </span>
                </>
              )}
            </div>
            <div className="flex flex-col items-center gap-0.5">
              <div className="w-1 h-1 rounded-full bg-slate-300" />
              <div className="w-1 h-1 rounded-full bg-slate-300" />
            </div>
            <div className="flex flex-col items-center">
              {scoresExist ? (
                <span className="text-3xl sm:text-4xl font-black text-slate-800 tabular-nums">
                  {game.homeScore}
                </span>
              ) : game.predictions && game.predictions.home.prob_win !== null && (
                <>
                  <span className="text-3xl sm:text-4xl font-black text-slate-800 tabular-nums">
                    {(game.predictions.home.prob_win * 100).toFixed(0)}%
                  </span>
                  <span className="text-[11px] font-bold text-blue-500 mt-0.5 tabular-nums">
                    {game.moneyline?.home}
                  </span>
                </>
              )}
            </div>
          </div>

          {scoresExist ?
            game.gameState === "LIVE" ? (
              <p className="text-[10px] font-semibold tracking-widest text-slate-400 uppercase">
                Game in Progress
              </p>
            ) : (
              <p className="text-[10px] font-semibold tracking-widest text-slate-400 uppercase">
                Final Score
              </p>
            ) : (
              <p className="text-[10px] font-semibold tracking-widest text-slate-400 uppercase">
                Predicted Win Probability
              </p>
            )}
          {game.moneyline && !scoresExist && (
            <>
              <p className="text-[10px] font-semibold tracking-widest text-slate-400 uppercase">
                Current Vegas Moneyline
              </p>
              {game.moneyline.best_away != null && game.moneyline.best_home != null && (
                <p className="text-[10px] text-slate-400 text-center leading-snug tabular-nums">
                  Best: {formatOdds(game.moneyline.best_away)} {formatBook(game.moneyline.best_away_book)}
                  {" · "}
                  {formatOdds(game.moneyline.best_home)} {formatBook(game.moneyline.best_home_book)}
                </p>
              )}
            </>
          )}
          <p className="text-xs text-slate-500 font-medium text-center leading-snug">
            📍 {game.venue}
          </p>
        </div>

        <TeamCard team={game.homeTeam} type="Home" />

      </div>
    </div>
  );
};
