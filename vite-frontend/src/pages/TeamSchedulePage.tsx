import type { FC } from "react";
import { useEffect, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import { useTeamNextFive } from "../hooks/useTeamNextFive";
import type { Team, TeamScheduledGame } from "../types/teams";
import { daysBetween, splitTeamName } from "../utils/gameStatus";
import { RinkHero } from "../components/rinkboard/RinkHero";
import { BoardGameCard } from "../components/rinkboard/BoardGameCard";
import { STRONG_EDGE_POINTS } from "../components/rinkboard/EdgeChip";
import { StretchChart, type StretchGame } from "../components/rinkboard/StretchChart";
import { ScheduleRow } from "../components/rinkboard/ScheduleRow";

// how many games the stretch chart covers, starting with the next one
const STRETCH_GAMES = 8;

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** "4 at home · 4 on the road · 2 back-to-backs" */
const summary = (homeGames: number, roadGames: number, backToBacks: number): string =>
  [
    `${homeGames} at home`,
    `${roadGames} on the road`,
    backToBacks > 0 && plural(backToBacks, "back-to-back", "back-to-backs"),
  ]
    .filter(Boolean)
    .join(" · ");

/** The coach's note on the stretch: the game the model likes the team least in, when it's an underdog there. */
const toughestNote = (stretch: StretchGame[]): string | null => {
  const priced = stretch.filter((g) => g.winProb !== null);
  if (priced.length < 3) return null;
  const worst = priced.reduce((a, b) => (b.winProb! < a.winProb! ? b : a));
  if (worst.winProb! >= 0.5) return null;
  const tag = worst.home ? `vs ${worst.game.awayTeam.tricode}` : `@ ${worst.game.homeTeam.tricode}`;
  return `toughest one: ${tag}`;
};

export const TeamSchedulePage: FC = () => {
  const { tricode: param } = useParams();
  const tricode = param!.toUpperCase();
  const { games, loading, loadingMore, hasMore, loadMore, error } = useTeamNextFive(param!);
  const sentinelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) loadMore();
      },
      { rootMargin: "200px" }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [loadMore]);

  const isHome = (g: TeamScheduledGame) => g.homeTeam.tricode === tricode;
  const first = games[0];
  const team: Team | null = first ? (isHome(first) ? first.homeTeam : first.awayTeam) : null;
  const { city, nickname } = team ? splitTeamName(team.name) : { city: "", nickname: tricode };

  // a back-to-back: the day after the team's previous game (unknown for the first game loaded)
  const backToBack = games.map((g, i) => i > 0 && daysBetween(games[i - 1].time, g.time) === 1);
  const homeGames = games.filter(isHome).length;

  const stretch: StretchGame[] = games.slice(0, STRETCH_GAMES).map((game) => {
    const home = isHome(game);
    const side = home ? game.predictions?.home : game.predictions?.away;
    return { game, home, winProb: side?.prob_win ?? null };
  });
  const coachsPick = !!first?.edge && first.edge.points >= STRONG_EDGE_POINTS;

  return (
    <div className="bd-page">
      <main className="bd-main">
        <RinkHero
          labelledBy="team-title"
          left={
            <>
              <div className="bd-row" style={{ gap: 8 }}>
                <Link to="/teams" className="bd-icon-btn" aria-label="All teams">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true">
                    <path d="M15 5l-7 7 7 7" />
                  </svg>
                </Link>
                <span className="bd-muted" style={{ fontWeight: 700 }}>
                  Schedule{city && ` · ${city}`}
                </span>
              </div>
              <div className="bd-row" style={{ gap: 16 }}>
                {team && <img className="bd-team-logo" src={team.logoUrl} alt={team.name} />}
                <h1 id="team-title" className="bd-display-xl">
                  {nickname.split(" ").map((word, i) => (
                    <span key={i}>
                      {i > 0 && <br />}
                      {word}
                    </span>
                  ))}
                </h1>
              </div>
            </>
          }
          right={
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
              {games.length > 0 ? (
                <>
                  <span className="bd-display-xl" style={{ textTransform: "none" }}>
                    {plural(games.length, "game", "games")}
                  </span>
                  <span className="bd-muted" style={{ fontWeight: 600 }}>
                    {summary(homeGames, games.length - homeGames, backToBack.filter(Boolean).length)}
                  </span>
                </>
              ) : (
                <span className="bd-muted" style={{ fontWeight: 600 }}>
                  {loading ? "Setting up the schedule" : ""}
                </span>
              )}
              <Link to={`/roster/${tricode}`} className="bd-btn" style={{ marginTop: 6 }}>
                Roster
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true">
                  <path d="M9 5l7 7-7 7" />
                </svg>
              </Link>
            </div>
          }
        />

        {loading ? (
          <p className="bd-empty" role="status">Loading the schedule</p>
        ) : error && games.length === 0 ? (
          <p className="bd-empty" role="alert">The schedule didn't load. Check that the API is up, then refresh the page.</p>
        ) : games.length === 0 ? (
          <p className="bd-empty">No games left on the schedule.</p>
        ) : (
          <>
            <section className="bd-section" aria-labelledby="next-heading">
              <div className="bd-section-head">
                <h2 id="next-heading" className="bd-heading">
                  Next up
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
              <div className="bd-grid">
                <BoardGameCard game={first} coachsPick={coachsPick} showDate receivedAt={0} now={0} />
                <StretchChart teamName={nickname} games={stretch} note={toughestNote(stretch)} />
              </div>
            </section>

            {games.length > 1 && (
              <section className="bd-section" aria-labelledby="ahead-heading">
                <div className="bd-section-head">
                  <h2 id="ahead-heading" className="bd-heading">
                    The road ahead
                  </h2>
                  <span className="bd-muted" style={{ fontSize: 13 }}>
                    Times in your time zone. Odds firm up as puck drop gets closer.
                  </span>
                </div>
                <ol className="bd-sched">
                  {games.slice(1).map((game, i) => (
                    <ScheduleRow key={game.id} game={game} home={isHome(game)} backToBack={backToBack[i + 1]} />
                  ))}
                </ol>
                {hasMore && <div ref={sentinelRef} style={{ height: 1 }} />}
                <p className="bd-label bd-sched-more" role="status">
                  {loadingMore
                    ? "Loading more games"
                    : error
                      ? "More games didn't load. Refresh the page to try again."
                      : hasMore
                        ? "More games load as you scroll"
                        : "That's the rest of the schedule"}
                </p>
              </section>
            )}
          </>
        )}
      </main>
    </div>
  );
};

export default TeamSchedulePage;
