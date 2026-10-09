import type { FC } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useDateGames } from "../hooks/useDateGames";
import { useNow } from "../hooks/useNow";
import type { TeamScheduledGame } from "../types/teams";
import { gamePhase, type GamePhase } from "../utils/gameStatus";
import { RinkHero } from "../components/rinkboard/RinkHero";
import { ChevronButton } from "../components/rinkboard/ChevronButton";
import { BoardGameCard } from "../components/rinkboard/BoardGameCard";
import { STRONG_EDGE_POINTS } from "../components/rinkboard/EdgeChip";

// while a game is on (or about to be), refetch the board this often; the server polls the NHL feed on its own
// interval (LIVE_SCORES_POLL_MINUTES) and caches it, so this only picks up its updates
const LIVE_REFRESH_MS = 60_000;
const SOON_MS = 15 * 60_000;

const toDateParam = (d: Date): string => {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}${m}${day}`;
};

const parseDate = (date: string): Date => {
  if (date === "today") return new Date();
  return new Date(
    parseInt(date.substring(0, 4)),
    parseInt(date.substring(4, 6)) - 1,
    parseInt(date.substring(6, 8))
  );
};

const dayLabel = (d: Date): string => {
  const weekday = d.toLocaleDateString("en-US", { weekday: "short" });
  const monthDay = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return `${weekday} · ${monthDay}`;
};

// the board's order: games on now, then still to come (by puck drop), then finals
const PHASE_ORDER: Record<GamePhase, number> = { live: 0, pre: 1, final: 2 };

const orderGames = (games: TeamScheduledGame[]): TeamScheduledGame[] =>
  [...games].sort(
    (a, b) =>
      PHASE_ORDER[gamePhase(a)] - PHASE_ORDER[gamePhase(b)] ||
      new Date(a.time).getTime() - new Date(b.time).getTime()
  );

/** The day's single best pick: the biggest strong edge among games still to drop the puck. */
const coachsPickId = (games: TeamScheduledGame[]): number | null => {
  let best: TeamScheduledGame | null = null;
  for (const g of games) {
    if (gamePhase(g) !== "pre" || !g.edge || g.edge.points < STRONG_EDGE_POINTS) continue;
    if (!best || g.edge.points > best.edge!.points) best = g;
  }
  return best?.id ?? null;
};

const summary = (games: TeamScheduledGame[]): string => {
  const count = { live: 0, pre: 0, final: 0 };
  games.forEach((g) => count[gamePhase(g)]++);
  return [
    count.live > 0 && `${count.live} live`,
    count.pre > 0 && `${count.pre} still to drop the puck`,
    count.final > 0 && `${count.final} final`,
  ]
    .filter(Boolean)
    .join(" · ");
};

const needsRefresh = (games: TeamScheduledGame[]): boolean =>
  games.some((g) => {
    const phase = gamePhase(g);
    return phase === "live" || (phase === "pre" && new Date(g.time).getTime() - Date.now() < SOON_MS);
  });

export const DailySchedulePage: FC = () => {
  const { date } = useParams();
  const navigate = useNavigate();
  const isToday = date === "today";
  const currentDate = parseDate(date!);

  // refreshed only while something is happening; a quiet board is fetched once
  const { data: games, loading, error, receivedAt } = useDateGames(date!, LIVE_REFRESH_MS, needsRefresh);
  const inIntermission = !!games?.some((g) => gamePhase(g) === "live" && g.live?.inIntermission);
  const now = useNow(inIntermission ? 1000 : null);

  const step = (days: number) => {
    const d = new Date(currentDate);
    d.setDate(d.getDate() + days);
    navigate(`/schedule/${toDateParam(d)}`);
  };

  const ordered = games ? orderGames(games) : [];
  const pick = coachsPickId(ordered);
  const gameCount = games?.length ?? 0;

  return (
    <div className="bd-page">
      <main className="bd-main">
        <RinkHero
          labelledBy="board-title"
          left={
            <>
              <div className="bd-row" style={{ gap: 8 }}>
                <ChevronButton direction="previous" label="Previous day" onClick={() => step(-1)} />
                <ChevronButton direction="next" label="Next day" onClick={() => step(1)} />
                <span className="bd-muted" style={{ fontWeight: 700 }}>
                  {dayLabel(currentDate)}
                </span>
              </div>
              <h1 id="board-title" className="bd-display-xl">
                {isToday ? (
                  <>
                    Tonight
                    <br />
                    on the ice
                  </>
                ) : (
                  <>
                    On the ice
                    <br />
                    {currentDate.toLocaleDateString("en-US", { weekday: "long" })}
                  </>
                )}
              </h1>
            </>
          }
          right={
            games ? (
              <>
                <span className="bd-display-xl" style={{ textTransform: "none" }}>
                  {gameCount === 0 ? "No games" : `${gameCount} ${gameCount === 1 ? "game" : "games"}`}
                </span>
                {gameCount > 0 && (
                  <span className="bd-muted" style={{ fontWeight: 600 }}>
                    {summary(games)}
                  </span>
                )}
              </>
            ) : (
              <span className="bd-muted" style={{ fontWeight: 600 }}>
                {loading ? "Setting up the board" : ""}
              </span>
            )
          }
        />

        <section className="bd-section" aria-labelledby="board-heading">
          <div className="bd-section-head">
            <h2 id="board-heading" className="bd-heading">
              The board
            </h2>
            <div className="bd-legend">
              <span>
                <i className="bd-swatch" style={{ background: "var(--blue-line)" }} />
                Away
              </span>
              <span>
                <i className="bd-swatch" style={{ background: "var(--goal-red)" }} />
                Home
              </span>
              <span>
                <i className="bd-swatch" style={{ background: "var(--ink)", borderRadius: "50%" }} />
                Puck sits at the model's win %
              </span>
            </div>
          </div>

          {loading ? (
            <p className="bd-empty" role="status">Loading the board</p>
          ) : error || !games ? (
            <p className="bd-empty" role="alert">The board didn't load. Check that the API is up, then refresh the page.</p>
          ) : gameCount === 0 ? (
            <p className="bd-empty">No puck drops on this day.</p>
          ) : (
            <div className="bd-grid">
              {ordered.map((game) => (
                <BoardGameCard
                  key={game.id}
                  game={game}
                  coachsPick={game.id === pick}
                  receivedAt={receivedAt}
                  now={Math.max(now, receivedAt)}
                />
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
};

export default DailySchedulePage;
