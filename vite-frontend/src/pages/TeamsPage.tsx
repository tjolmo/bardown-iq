import type { FC } from "react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { RinkHero } from "../components/rinkboard/RinkHero";
import { STRONG_EDGE_POINTS } from "../components/rinkboard/EdgeChip";
import { useStandings } from "../hooks/useStandings";
import { useDateGames } from "../hooks/useDateGames";
import { NHL_CONFERENCES } from "../data/nhlDivisions";
import type { TeamScheduledGame, TeamStandingsRow } from "../types/teams";
import { daysBetween, formatEdge, localTime } from "../utils/gameStatus";

type Conference = "All" | "East" | "West";

const CONFERENCES: { key: Conference; name: string; divisions: string[] }[] = [
  { key: "East", name: "Eastern Conference", divisions: ["Atlantic", "Metropolitan"] },
  { key: "West", name: "Western Conference", divisions: ["Central", "Pacific"] },
];

// the division's top three get in on their own; the line under the third row marks it
const DIVISION_CUT = 3;

// the static map, for a team the standings feed hasn't placed (the feed down, or a team it doesn't list)
const STATIC_DIVISION: Record<string, string> = Object.fromEntries(
  NHL_CONFERENCES.flatMap((c) =>
    c.divisions.flatMap((d) => d.tricodes.map((tc) => [tc, d.name.replace(" Division", "")]))
  )
);

const divisionOf = (row: TeamStandingsRow): string =>
  row.standing?.division ?? STATIC_DIVISION[row.team.tricode] ?? "Other";

/** "2026–27" from the feed's 20262027, or from today's date while the feed hasn't answered. */
const seasonLabel = (seasonId: number | null): string => {
  if (seasonId) return `${Math.floor(seasonId / 10000)}–${String(seasonId % 10000).slice(-2)}`;
  const now = new Date();
  const start = now.getMonth() >= 8 ? now.getFullYear() : now.getFullYear() - 1;
  return `${start}–${String(start + 1).slice(-2)}`;
};

/** "Tonight", "Tomorrow", "Sun" within the week, else "Oct 18", in the visitor's time zone. */
const gameDay = (iso: string): string => {
  const days = daysBetween(new Date().toISOString(), iso);
  if (days <= 0) return "Tonight";
  if (days === 1) return "Tomorrow";
  const d = new Date(iso);
  return days < 7
    ? d.toLocaleDateString("en-US", { weekday: "short" })
    : d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
};

const record = (row: TeamStandingsRow): string =>
  row.standing ? `${row.standing.wins}-${row.standing.losses}-${row.standing.otLosses}` : "—";

/** The edge for this team's side of its next game, when the model likes it. */
const ownEdge = (row: TeamStandingsRow): number | null =>
  row.nextGame?.edge && row.nextGame.edge.tri_code === row.team.tricode ? row.nextGame.edge.points : null;

/** The coach's note on a division: its team the model likes most against tonight's moneyline, when it's a strong edge. */
const divisionNote = (rows: TeamStandingsRow[]): string | null => {
  const tonight = rows
    .map((r) => ({ r, edge: ownEdge(r) }))
    .filter((x) => x.edge !== null && x.edge >= STRONG_EDGE_POINTS && x.r.nextGame && gameDay(x.r.nextGame.startTime) === "Tonight");
  if (tonight.length === 0) return null;
  const best = tonight.reduce((a, b) => (b.edge! > a.edge! ? b : a));
  return `${best.r.nickname.toLowerCase()} are the value tonight`;
};

const matches = (row: TeamStandingsRow, needle: string): boolean =>
  !needle ||
  row.team.name.toLowerCase().includes(needle) ||
  row.team.tricode.toLowerCase() === needle ||
  row.city.toLowerCase().includes(needle) ||
  row.nickname.toLowerCase().includes(needle);

const byRank = (a: TeamStandingsRow, b: TeamStandingsRow): number =>
  (a.standing?.divisionRank ?? 99) - (b.standing?.divisionRank ?? 99) || a.team.tricode.localeCompare(b.team.tricode);

const TeamRow: FC<{ row: TeamStandingsRow; rank: number }> = ({ row, rank }) => {
  const next = row.nextGame;
  const side = next ? (next.home ? "tm-home" : "tm-away") : "";
  const edge = ownEdge(row);
  const pts = row.standing ? row.standing.points : "—";
  return (
    <div className={`tm-row${rank === DIVISION_CUT ? " cut" : ""}`}>
      <span className="tm-rank">{rank}</span>
      <Link className="tm-team" to={`/roster/${row.team.tricode}`} title={row.team.name}>
        <img src={row.team.logoUrl} alt="" />
        <span className="tm-team-text">
          <span className="tm-city">{row.city}</span>
          <span className="tm-nick">{row.nickname}</span>
          <span className="tm-rec-sm">{record(row)} · {pts} pts</span>
        </span>
      </Link>
      <span className="tm-rec tm-desk">{record(row)}</span>
      <span className="tm-pts tm-r tm-desk">{pts}</span>
      {next ? (
        <Link className="tm-next" to={`/schedule/team/${row.team.tricode}`} title={`${next.home ? "vs" : "at"} ${next.opponent.name}`}>
          <span className={`tm-vs ${side}`}>{next.home ? "vs" : "at"}</span>
          <img src={next.opponent.logoUrl} alt={next.opponent.name} />
          <span className="tm-when">
            <strong>{gameDay(next.startTime)}</strong>
            <span>{localTime(next.startTime)}</span>
          </span>
        </Link>
      ) : (
        <span className="tm-next bd-muted">None scheduled</span>
      )}
      <span className="tm-model">
        {next && next.probWin !== null ? (
          <span className={`tm-win ${side}`}>{Math.round(next.probWin * 100)}%</span>
        ) : (
          <span className="tm-win bd-muted">—</span>
        )}
        {edge !== null && (
          <span className={`tm-edge${edge >= STRONG_EDGE_POINTS ? " strong" : ""}`}>{formatEdge(edge)}</span>
        )}
      </span>
    </div>
  );
};

const DivisionCard: FC<{ name: string; rows: TeamStandingsRow[]; note: string | null }> = ({ name, rows, note }) => (
  <article className="bd-card tm-card" aria-label={`${name} Division`}>
    <div className="tm-div-head">
      <h3 className="tm-div-name">{name}</h3>
      {note && <span className="bd-note" style={{ fontSize: 20 }}>{note}</span>}
    </div>
    <div className="tm-table">
      <div className="tm-cols">
        <span>#</span>
        <span>Team</span>
        <span className="tm-desk">W-L-OT</span>
        <span className="tm-r tm-desk">Pts</span>
        <span>Next game</span>
        <span className="tm-r">Model</span>
      </div>
      {rows.map((row) => (
        <TeamRow key={row.team.tricode} row={row} rank={row.standing?.divisionRank ?? rows.indexOf(row) + 1} />
      ))}
    </div>
  </article>
);

/** The hero's right zone: who plays tonight, and the way to the board. */
const TonightZone: FC<{ games: TeamScheduledGame[] | null }> = ({ games }) => {
  const count = games?.length ?? 0;
  const first = games && count > 0 ? games.reduce((a, b) => (b.time < a.time ? b : a)) : null;
  return (
    <>
      <span className="bd-label" style={{ alignSelf: "flex-end" }}>On the ice tonight</span>
      {count > 0 && (
        <div className="tm-tonight">
          {games!.map((g) => (
            <span className="tm-pair" key={g.id} title={`${g.awayTeam.name} at ${g.homeTeam.name}`}>
              <img src={g.awayTeam.logoUrl} alt={g.awayTeam.name} />
              <span>at</span>
              <img src={g.homeTeam.logoUrl} alt={g.homeTeam.name} />
            </span>
          ))}
        </div>
      )}
      <span className="bd-muted" style={{ fontSize: 13, fontWeight: 600 }}>
        {games === null
          ? "Loading tonight's games"
          : count === 0
            ? "No games tonight"
            : `${count} ${count === 1 ? "game" : "games"} · first puck drop ${localTime(first!.time)}`}
      </span>
      <Link to="/schedule/today" className="bd-btn" style={{ alignSelf: "flex-end", marginTop: 4 }}>
        Tonight's slate
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true">
          <path d="M9 5l7 7-7 7" />
        </svg>
      </Link>
    </>
  );
};

// a phone starts on one conference: both at once is a long scroll
const startingConference = (): Conference =>
  typeof window !== "undefined" && window.matchMedia("(max-width: 680px)").matches ? "East" : "All";

/** The league: every team by division, ranked on points, with its next game and the model's call on it. */
export const TeamsPage: FC = () => {
  const { data, loading, error } = useStandings();
  const { data: tonight } = useDateGames("today");
  const [conference, setConference] = useState<Conference>(startingConference);
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();

  const board = useMemo(() => {
    const rows = data?.teams ?? [];
    return CONFERENCES
      .filter((c) => conference === "All" || conference === c.key)
      .map((c) => ({
        ...c,
        divisions: c.divisions
          .map((name) => {
            const all = rows.filter((r) => divisionOf(r) === name).sort(byRank);
            return { name, rows: all.filter((r) => matches(r, needle)), note: needle ? null : divisionNote(all) };
          })
          .filter((d) => d.rows.length > 0),
      }))
      .filter((c) => c.divisions.length > 0);
  }, [data, conference, needle]);

  return (
    <div className="bd-page">
      <main className="bd-main">
        <RinkHero
          labelledBy="teams-title"
          left={
            <>
              <span className="bd-label" style={{ alignSelf: "flex-start" }}>
                {seasonLabel(data?.seasonId ?? null)} regular season
              </span>
              <h1 id="teams-title" className="bd-display-xl">The league</h1>
              <p className="bd-muted" style={{ margin: 0, maxWidth: 400 }}>
                32 teams by division, ranked on points. Pick one for its lines, its schedule and the model's odds on its next game.
              </p>
            </>
          }
          right={<TonightZone games={tonight} />}
        />

        <div className="tm-tools">
          <div className="tm-tools-left">
            <div className="tm-seg" role="group" aria-label="Conference">
              {(["All", "East", "West"] as Conference[]).map((c) => (
                <button key={c} type="button" aria-pressed={conference === c} onClick={() => setConference(c)}>
                  {c}
                </button>
              ))}
            </div>
            <label className="bd-search tm-find">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true">
                <circle cx="11" cy="11" r="7" />
                <path d="M20 20l-3.5-3.5" />
              </svg>
              <span className="bd-sr">Find a team</span>
              <input type="search" placeholder="Find a team" value={query} onChange={(e) => setQuery(e.target.value)} />
            </label>
          </div>
          <div className="bd-legend">
            <span><i className="bd-swatch" style={{ background: "var(--goal-red)" }} />vs · at home</span>
            <span><i className="bd-swatch" style={{ background: "var(--blue-line)" }} />at · on the road</span>
            <span><b className="tm-edge strong">+4.1</b>edge on the moneyline</span>
            <span><i className="bd-swatch" style={{ height: 2, background: "var(--ink)" }} />top three in the division</span>
          </div>
          {data && data.stale && data.asOf && (
            <span className="tm-asof">NHL.com isn't answering: standings as of {localTime(data.asOf)}.</span>
          )}
          {data && !data.asOf && (
            <span className="tm-asof">The standings feed hasn't answered yet, so records are missing for now.</span>
          )}
        </div>

        {loading ? (
          <p className="bd-empty" role="status">Loading the standings</p>
        ) : error || !data ? (
          <p className="bd-empty" role="alert">The teams didn't load. Check that the API is up, then refresh the page.</p>
        ) : board.length === 0 ? (
          <p className="bd-empty">No team matches “{query.trim()}”. Try a city or a nickname.</p>
        ) : (
          board.map((c) => (
            <section className="tm-conf" key={c.key} aria-label={c.name}>
              <div className="tm-conf-head">
                <h2 className="bd-heading">{c.name}</h2>
                <span className="bd-label">Model % is the win chance for the next game</span>
              </div>
              <div className="bd-grid">
                {c.divisions.map((d) => (
                  <DivisionCard key={d.name} name={d.name} rows={d.rows} note={d.note} />
                ))}
              </div>
            </section>
          ))
        )}
      </main>
    </div>
  );
};

export default TeamsPage;
