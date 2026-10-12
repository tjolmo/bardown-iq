import type { CSSProperties, FC, ReactNode } from "react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { RinkHero } from "../components/rinkboard/RinkHero";
import { useTopGoalies, useTopSkaters } from "../hooks/useTopPlayers";
import type { GoalieSort, PositionFilter, SkaterSort, TopGoalie, TopPlayer, TopSkater } from "../types/player";
import type { TeamLookup } from "../types/teams";
import { gameDay, POSITION_NAMES, teamOf } from "../utils/playerStats";
import { splitTeamName } from "../utils/gameStatus";

type PlayerType = "skaters" | "goalies";

const DEFAULT_HEADSHOT = "https://assets.nhle.com/mugs/nhl/default-player.png";

// the table shows this many to start, and the button under it adds a page at a time
const FIRST_PAGE = 16;
const PAGE = 25;

// the goalies board's games-played floor; one game early in the season says little
const DEFAULT_MIN_GAMES = 2;
const MIN_GAMES_CHOICES = [1, 2, 5, 10];

const SHORT_POSITION: Record<string, string> = { C: "C", L: "LW", R: "RW", D: "D", G: "G" };

// each stat a board can rank on, and how its column reads
interface StatColumn<T> {
  key: string;
  label: string;        // the column header and the sort pill
  value: (p: T) => string;
  muted?: boolean;      // context more than content: greyed in the table
  sortable?: boolean;
}

const fixed = (n: number | null, digits: number): string => (n === null ? "—" : n.toFixed(digits));
const savePct = (n: number | null): string => (n === null ? "—" : n.toFixed(3).replace(/^0/, ""));
const signed = (n: number, digits: number): string => `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(digits)}`;

const SKATER_COLUMNS: StatColumn<TopSkater>[] = [
  { key: "games", label: "GP", value: (s) => String(s.games), muted: true },
  { key: "goals", label: "G", value: (s) => String(s.goals), sortable: true },
  { key: "assists", label: "A", value: (s) => String(s.assists), sortable: true },
  { key: "points", label: "PTS", value: (s) => String(s.points), sortable: true },
  { key: "points_per_game", label: "PTS/GP", value: (s) => fixed(s.points_per_game, 2), sortable: true },
  { key: "x_goals", label: "xG", value: (s) => fixed(s.x_goals, 1), muted: true, sortable: true },
  { key: "shots_on_goal", label: "SOG", value: (s) => String(s.shots_on_goal), muted: true },
  { key: "toi_per_game", label: "TOI", value: (s) => fixed(s.toi_per_game, 1), muted: true },
  { key: "pp_points", label: "PPP", value: (s) => String(s.pp_points), muted: true, sortable: true },
];

const GOALIE_COLUMNS: StatColumn<TopGoalie>[] = [
  { key: "games", label: "GP", value: (g) => String(g.games), muted: true },
  { key: "shots_faced", label: "Shots", value: (g) => String(g.shots_faced), muted: true, sortable: true },
  { key: "goals_against", label: "GA", value: (g) => String(g.goals_against) },
  { key: "save_percentage", label: "SV%", value: (g) => savePct(g.save_percentage), sortable: true },
  { key: "gaa", label: "GAA", value: (g) => fixed(g.gaa, 2), sortable: true },
  { key: "gsax", label: "GSAx", value: (g) => signed(g.gsax, 1), sortable: true },
  { key: "high_danger_shots", label: "HD shots", value: (g) => String(g.high_danger_shots), muted: true },
];

const SKATER_SORTS = new Set<string>(SKATER_COLUMNS.filter((c) => c.sortable).map((c) => c.key));
const GOALIE_SORTS = new Set<string>(GOALIE_COLUMNS.filter((c) => c.sortable).map((c) => c.key));

const fullName = (p: TopPlayer): string => `${p.first_name} ${p.last_name}`;

/** "2026–27" from the season's start year. */
const seasonLabel = (season: number): string => `${season}–${String(season + 1).slice(-2)}`;

const Headshot: FC<{ player: TopPlayer; size: number; className?: string }> = ({ player, size, className }) => (
  <span className={`lb-face${className ? ` ${className}` : ""}`} style={{ width: size, height: size }}>
    <img
      src={player.headshot ?? DEFAULT_HEADSHOT}
      alt=""
      loading="lazy"
      onError={(e) => {
        const img = e.currentTarget;
        if (img.src !== DEFAULT_HEADSHOT) img.src = DEFAULT_HEADSHOT;
      }}
    />
  </span>
);

/** The team's logo beside its tricode: the logo is the identity, the tricode the label in a tight spot. */
const TeamChip: FC<{ tricode: string; teams: TeamLookup }> = ({ tricode, teams }) => {
  const team = teamOf(teams, tricode);
  return (
    <span className="lb-team" title={team.name}>
      <img src={team.logoUrl} alt={team.name === tricode ? "" : team.name} />
      {tricode}
    </span>
  );
};

const PlayerLink: FC<{ player: TopPlayer; children: ReactNode; className?: string }> = ({ player, children, className }) => (
  <Link to={`/${player.position === "G" ? "goalie" : "player"}/${player.id}`} className={className}>
    {children}
  </Link>
);

/** Points in each game as bars on the board, scaled to the best game among the top three. */
const GameBars: FC<{ points: number[]; max: number }> = ({ points, max }) => (
  <div className="lb-bars" role="img" aria-label={`Points by game: ${points.join(", ")}`}>
    {points.map((p, i) => (
      <i key={i} style={{ height: `${Math.max(4, Math.round((p / max) * 100))}%` }} />
    ))}
  </div>
);

/** Two tracks: the goals the shots faced should have produced, dashed, over the goals that went in. */
const ExpectedVsAllowed: FC<{ expected: number; allowed: number; max: number }> = ({ expected, allowed, max }) => (
  <div className="lb-tracks">
    <div className="lb-track-row">
      <span className="bd-label">Expected</span>
      <span className="lb-track"><i className="lb-track-ghost" style={{ width: `${(expected / max) * 100}%` }} /></span>
      <strong>{expected.toFixed(1)}</strong>
    </div>
    <div className="lb-track-row">
      <span className="bd-label">Allowed</span>
      <span className="lb-track"><i className="lb-track-fill" style={{ width: `${(allowed / max) * 100}%` }} /></span>
      <strong>{allowed}</strong>
    </div>
  </div>
);

interface PodiumCardProps<T extends TopPlayer> {
  player: T;
  rank: number;
  teams: TeamLookup;
  big: string;
  bigLabel: string;
  chips: string[];
  figure: ReactNode;
  stats: { label: string; value: string }[];
  note: string | null;
  stacked?: boolean;    // the figure under the number rather than beside it
}

function PodiumCard<T extends TopPlayer>({ player, rank, teams, big, bigLabel, chips, figure, stats, note, stacked }: PodiumCardProps<T>) {
  return (
    <PlayerLink player={player} className="bd-card lb-podium-card">
      {note && <span className="bd-note-tag">{note}</span>}
      <div className="lb-podium-head">
        <span className="lb-podium-rank">{rank}</span>
        <Headshot player={player} size={64} />
        <div className="lb-podium-who">
          <span className="lb-name lb-name-lg">{fullName(player)}</span>
          <span className="lb-chips">
            <TeamChip tricode={player.current_team_tri_code} teams={teams} />
            {chips.map((c) => <span className="lb-chip" key={c}>{c}</span>)}
          </span>
        </div>
      </div>
      <div className={`lb-podium-body${stacked ? " lb-stack" : ""}`}>
        <div className="lb-podium-big">
          <span className="bd-score lb-big">{big}</span>
          <span className="bd-label">{bigLabel}</span>
        </div>
        {figure}
      </div>
      <div className="lb-podium-stats">
        {stats.map((s) => (
          <div key={s.label}>
            <span className="bd-label">{s.label}</span>
            <strong>{s.value}</strong>
          </div>
        ))}
      </div>
    </PlayerLink>
  );
}

interface BoardProps<T extends TopPlayer> {
  rows: T[];
  firstRank: number;
  columns: StatColumn<T>[];
  sort: string;
  onSort: (key: string) => void;
  teams: TeamLookup;
  subline: (p: T) => string;    // what a phone shows under the name instead of the columns
  label: string;
}

/** Everyone under the podium, one row each; the column the board is ranked on is marked and sits with the name on a phone. */
function Board<T extends TopPlayer>({ rows, firstRank, columns, sort, onSort, teams, subline, label }: BoardProps<T>) {
  const [visible, setVisible] = useState(FIRST_PAGE);
  const shown = rows.slice(0, visible);
  const cell = (c: StatColumn<T>) => `lb-c${c.key === sort ? " lb-hl" : " lb-desk"}${c.muted ? " lb-dim" : ""}`;
  return (
    <>
      <div className="bd-card lb-board" role="table" aria-label={label} style={{ "--lb-cols": columns.length } as CSSProperties}>
        <div className="lb-tr lb-th" role="row">
          <span className="lb-c" role="columnheader">#</span>
          <span className="lb-c lb-c-player" role="columnheader">Player</span>
          {columns.map((c) => (
            <span key={c.key} className={cell(c)} role="columnheader" aria-sort={c.key === sort ? "descending" : undefined}>
              {c.sortable ? (
                <button type="button" className="lb-sort" onClick={() => onSort(c.key)} aria-pressed={c.key === sort}>{c.label}</button>
              ) : (
                c.label
              )}
            </span>
          ))}
        </div>
        {shown.map((p, i) => (
          <div className="lb-tr" role="row" key={p.id}>
            <span className="lb-c lb-rank" role="cell">{firstRank + i}</span>
            <PlayerLink player={p} className="lb-c lb-c-player lb-player">
              <Headshot player={p} size={40} />
              <span className="lb-player-text">
                <span className="lb-name">{fullName(p)}</span>
                <span className="lb-player-sub">
                  <TeamChip tricode={p.current_team_tri_code} teams={teams} />
                  <span className="lb-desk">{SHORT_POSITION[p.position] ?? p.position}</span>
                  <span className="lb-phone">{subline(p)}</span>
                </span>
              </span>
            </PlayerLink>
            {columns.map((c) => (
              <span key={c.key} className={cell(c)} role="cell">{c.value(p)}</span>
            ))}
          </div>
        ))}
      </div>
      <div className="lb-board-foot">
        <span className="bd-muted" style={{ fontSize: 13 }}>
          {rows.length === 0 ? "Nobody qualifies yet" : `Showing ${shown.length} of ${rows.length}`}
        </span>
        {visible < rows.length && (
          <button type="button" className="bd-btn" onClick={() => setVisible((v) => v + PAGE)}>
            Show the next {Math.min(PAGE, rows.length - visible)}
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>
        )}
      </div>
    </>
  );
}

const Pills: FC<{ label: string; choices: { key: string; label: string }[]; value: string; onChange: (key: string) => void }> = ({ label, choices, value, onChange }) => (
  <div className="lb-pills" role="group" aria-label={label}>
    <span className="bd-label">{label}</span>
    <div className="lb-pills-row">
      {choices.map((c) => (
        <button key={c.key} type="button" className="pl-filter" aria-pressed={c.key === value} onClick={() => onChange(c.key)}>
          {c.label}
        </button>
      ))}
    </div>
  </div>
);

/** The leader at centre ice: who's on top of the board and by how much. */
const LeaderZone: FC<{ player: TopPlayer | null; teams: TeamLookup; chip: string; big: string; bigLabel: string; line: string; loading: boolean }> = ({
  player, teams, chip, big, bigLabel, line, loading,
}) => {
  if (!player) {
    return <span className="bd-muted" style={{ fontSize: 13, fontWeight: 600 }}>{loading ? "Loading the board" : "Nobody on the board yet"}</span>;
  }
  const team = teamOf(teams, player.current_team_tri_code);
  return (
    <div className="lb-leader">
      <Headshot player={player} size={130} className="lb-face-lead" />
      <div className="lb-leader-text">
        <span className="bd-chip bd-chip-final" style={{ alignSelf: "flex-start" }}>{chip}</span>
        <PlayerLink player={player} className="lb-name lb-name-xl">{fullName(player)}</PlayerLink>
        <span className="lb-leader-meta">
          <img src={team.logoUrl} alt="" />
          {team.name === player.current_team_tri_code ? team.name : splitTeamName(team.name).nickname}
          {" · "}
          {POSITION_NAMES[player.position] ?? player.position}
          {player.position === "G" && ` · catches ${player.shoots_catches === "R" ? "right" : "left"}`}
        </span>
        <span className="lb-leader-big">
          <span className="bd-score lb-big">{big}</span>
          <span className="bd-label">{bigLabel}</span>
        </span>
        <span className="bd-muted" style={{ fontSize: 13 }}>{line}</span>
      </div>
    </div>
  );
};

const TypeSwitch: FC<{ current: PlayerType; season: string }> = ({ current, season }) => (
  <div className="tm-seg lb-seg" role="group" aria-label="Player type">
    <Link to={`/top-players/skaters/${season}/50`} aria-current={current === "skaters" ? "page" : undefined}>Skaters</Link>
    <Link to={`/top-players/goalies/${season}/30`} aria-current={current === "goalies" ? "page" : undefined}>Goalies</Link>
  </div>
);

const throughLabel = (season: number, through: string | null): string =>
  `${seasonLabel(season)} regular season${through ? ` · through ${gameDay(through)}` : ""}`;

/** Skaters: how the leader stands against the next player on the board. */
const skaterLeaderLine = (rows: TopSkater[], sort: SkaterSort): string => {
  if (rows.length < 2) return "";
  const [lead, next] = rows;
  const col = SKATER_COLUMNS.find((c) => c.key === sort)!;
  if (lead[sort] === next[sort]) {
    const fewer = next.games - lead.games;
    return `Tied with ${fullName(next)}${fewer > 0 ? `, ${fewer} fewer ${fewer === 1 ? "game" : "games"} played` : ""}`;
  }
  const gap = lead[sort] - next[sort];
  return `${Number.isInteger(gap) ? gap : gap.toFixed(sort === "points_per_game" ? 2 : 1)} ${col.label} clear of ${fullName(next)}`;
};

/** The coach's note on the podium: the one finishing well over or under the chances, when it's by two goals or more. */
const skaterNote = (podium: TopSkater[]): Map<number, string> => {
  const notes = new Map<number, string>();
  const hot = podium.filter((s) => s.goals - s.x_goals >= 2).sort((a, b) => b.goals - b.x_goals - (a.goals - a.x_goals))[0];
  if (hot) notes.set(hot.id, `${hot.goals} goals on ${hot.x_goals.toFixed(1)} xG`);
  return notes;
};

const goalieNote = (podium: TopGoalie[]): Map<number, string> => {
  const notes = new Map<number, string>();
  const busiest = podium.length === 3 ? podium.reduce((a, b) => (b.shots_faced > a.shots_faced ? b : a)) : null;
  if (busiest && podium.every((g) => g === busiest || g.shots_faced < busiest.shots_faced)) notes.set(busiest.id, "most work of the three");
  return notes;
};

const SkatersPage: FC<{ season: string; n: number }> = ({ season, n }) => {
  const [params, setParams] = useSearchParams();
  const sort = (SKATER_SORTS.has(params.get("sort") ?? "") ? params.get("sort") : "points") as SkaterSort;
  const position = (["F", "D"].includes(params.get("position") ?? "") ? params.get("position") : "all") as PositionFilter;
  const { data, teams, loading, error } = useTopSkaters(season, n, sort, position);
  const set = (key: string, value: string, dflt: string) =>
    setParams((p) => {
      if (value === dflt) p.delete(key);
      else p.set(key, value);
      return p;
    }, { replace: true });

  const rows = data?.skaters ?? [];
  const col = SKATER_COLUMNS.find((c) => c.key === sort)!;
  const podium = rows.slice(0, 3);
  const bestGame = Math.max(1, ...podium.flatMap((s) => s.points_by_game));
  const notes = skaterNote(podium);
  const lead = rows[0] ?? null;
  const positionWord = position === "F" ? "forwards" : position === "D" ? "defencemen" : "skaters";

  return (
    <main className="bd-main">
      <RinkHero
        labelledBy="top-title"
        left={
          <>
            <span className="bd-label" style={{ alignSelf: "flex-start" }}>{data ? throughLabel(data.season, data.through) : "Regular season"}</span>
            <h1 id="top-title" className="bd-display-xl">Top<br />Skaters</h1>
            <p className="bd-muted" style={{ margin: 0, maxWidth: 340 }}>
              Every rostered skater's season, ranked on {col.label}. Change the stat to re-rank the board, or narrow it to forwards or defence.
            </p>
          </>
        }
        right={
          <LeaderZone
            player={lead}
            teams={teams}
            chip={position === "all" ? "Leads the league" : `Leads the ${positionWord}`}
            big={lead ? col.value(lead) : ""}
            bigLabel={lead ? `${col.label} in ${lead.games} GP` : ""}
            line={skaterLeaderLine(rows, sort)}
            loading={loading}
          />
        }
      />

      <div className="lb-tools">
        <TypeSwitch current="skaters" season={season} />
        <Pills
          label="Rank by"
          choices={SKATER_COLUMNS.filter((c) => c.sortable).map((c) => ({ key: c.key, label: c.label }))}
          value={sort}
          onChange={(k) => set("sort", k, "points")}
        />
        <Pills
          label="Position"
          choices={[{ key: "all", label: "ALL" }, { key: "F", label: "F" }, { key: "D", label: "D" }]}
          value={position}
          onChange={(k) => set("position", k, "all")}
        />
      </div>

      {error ? (
        <p className="bd-empty" role="alert">The board didn't load. Check that the API is up, then refresh the page.</p>
      ) : loading && !data ? (
        <p className="bd-empty" role="status">Loading the board</p>
      ) : rows.length === 0 ? (
        <p className="bd-empty">No {positionWord} have a game logged this season yet.</p>
      ) : (
        <>
          <section className="bd-section" aria-labelledby="podium-h">
            <div className="bd-section-head">
              <h2 id="podium-h" className="bd-heading">The top line</h2>
              <span className="bd-label">Bars are points in each game this season</span>
            </div>
            <div className="lb-podium">
              {podium.map((s, i) => (
                <PodiumCard
                  key={s.id}
                  player={s}
                  rank={i + 1}
                  teams={teams}
                  big={col.value(s)}
                  bigLabel={`${col.label} · ${s.games} GP`}
                  chips={[SHORT_POSITION[s.position] ?? s.position]}
                  figure={
                    <div className="lb-figure">
                      <GameBars points={s.points_by_game} max={bestGame} />
                      <span className="bd-label" style={{ fontSize: 11 }}>Game by game</span>
                    </div>
                  }
                  stats={[
                    { label: "G", value: String(s.goals) },
                    { label: "A", value: String(s.assists) },
                    { label: "PTS/GP", value: fixed(s.points_per_game, 2) },
                    { label: "TOI", value: fixed(s.toi_per_game, 1) },
                  ]}
                  note={notes.get(s.id) ?? null}
                />
              ))}
            </div>
          </section>

          {rows.length > 3 && (
            <section className="bd-section" aria-labelledby="board-h">
              <div className="bd-section-head">
                <h2 id="board-h" className="bd-heading">The board</h2>
                <span className="bd-label">TOI is minutes a game · PPP is power-play points · tap a column to re-rank</span>
              </div>
              <Board
                key={`${sort}-${position}`}
                rows={rows.slice(3)}
                firstRank={4}
                columns={SKATER_COLUMNS}
                sort={sort}
                onSort={(k) => set("sort", k, "points")}
                teams={teams}
                subline={(s) => `${SHORT_POSITION[s.position] ?? s.position} · ${s.games} GP · ${s.goals}G ${s.assists}A`}
                label="Top skaters"
              />
            </section>
          )}
        </>
      )}
    </main>
  );
};

const goalieLeaderLine = (g: TopGoalie): string =>
  `${savePct(g.save_percentage)} SV% · ${fixed(g.gaa, 2)} GAA · ${g.goals_against} ${g.goals_against === 1 ? "goal" : "goals"} on ${g.x_goals_against.toFixed(1)} expected`;

const GoaliesPage: FC<{ season: string; n: number }> = ({ season, n }) => {
  const [params, setParams] = useSearchParams();
  const sort = (GOALIE_SORTS.has(params.get("sort") ?? "") ? params.get("sort") : "gsax") as GoalieSort;
  const minParam = Number(params.get("min"));
  const minGames = MIN_GAMES_CHOICES.includes(minParam) ? minParam : DEFAULT_MIN_GAMES;
  const { data, teams, loading, error } = useTopGoalies(season, n, sort, minGames);
  const set = (key: string, value: string, dflt: string) =>
    setParams((p) => {
      if (value === dflt) p.delete(key);
      else p.set(key, value);
      return p;
    }, { replace: true });

  const rows = data?.goalies ?? [];
  const col = GOALIE_COLUMNS.find((c) => c.key === sort)!;
  const podium = rows.slice(0, 3);
  const mostGoals = Math.max(1, ...podium.flatMap((g) => [g.goals_against, g.x_goals_against]));
  const notes = goalieNote(podium);
  const lead = rows[0] ?? null;

  return (
    <main className="bd-main">
      <RinkHero
        labelledBy="top-title"
        left={
          <>
            <span className="bd-label" style={{ alignSelf: "flex-start" }}>{data ? throughLabel(data.season, data.through) : "Regular season"}</span>
            <h1 id="top-title" className="bd-display-xl">Top<br />Goalies</h1>
            <p className="bd-muted" style={{ margin: 0, maxWidth: 340 }}>
              {sort === "gsax"
                ? "Ranked on goals saved above expected: how many fewer went in than the shots faced should have produced. Save percentage is one tap away."
                : `Ranked on ${col.label}. Goals saved above expected, how many fewer went in than the shots faced should have produced, is one tap away.`}
            </p>
          </>
        }
        right={
          <LeaderZone
            player={lead}
            teams={teams}
            chip="Best in the crease"
            big={lead ? col.value(lead) : ""}
            bigLabel={lead ? `${col.label} in ${lead.games} GP` : ""}
            line={lead ? goalieLeaderLine(lead) : ""}
            loading={loading}
          />
        }
      />

      <div className="lb-tools">
        <TypeSwitch current="goalies" season={season} />
        <Pills
          label="Rank by"
          choices={GOALIE_COLUMNS.filter((c) => c.sortable).map((c) => ({ key: c.key, label: c.key === "shots_faced" ? "SHOTS FACED" : c.label }))}
          value={sort}
          onChange={(k) => set("sort", k, "gsax")}
        />
        <Pills
          label="Min. games"
          choices={MIN_GAMES_CHOICES.map((m) => ({ key: String(m), label: String(m) }))}
          value={String(minGames)}
          onChange={(k) => set("min", k, String(DEFAULT_MIN_GAMES))}
        />
      </div>

      {error ? (
        <p className="bd-empty" role="alert">The board didn't load. Check that the API is up, then refresh the page.</p>
      ) : loading && !data ? (
        <p className="bd-empty" role="status">Loading the board</p>
      ) : rows.length === 0 ? (
        <p className="bd-empty">No goalie has {minGames} {minGames === 1 ? "game" : "games"} logged this season yet. Lower the floor.</p>
      ) : (
        <>
          <section className="bd-section" aria-labelledby="podium-h">
            <div className="bd-section-head">
              <h2 id="podium-h" className="bd-heading">Standing on their heads</h2>
              <span className="bd-label">Dashed is goals expected from the shots faced; solid is goals allowed</span>
            </div>
            <div className="lb-podium">
              {podium.map((g, i) => (
                <PodiumCard
                  key={g.id}
                  player={g}
                  rank={i + 1}
                  teams={teams}
                  big={col.value(g)}
                  bigLabel={sort === "gsax" ? "Goals saved above expected" : `${col.label} · ${g.games} GP`}
                  chips={[`${g.games} GP`]}
                  figure={<ExpectedVsAllowed expected={g.x_goals_against} allowed={g.goals_against} max={mostGoals} />}
                  stacked
                  stats={[
                    { label: "SV%", value: savePct(g.save_percentage) },
                    { label: "GAA", value: fixed(g.gaa, 2) },
                    { label: "Shots", value: String(g.shots_faced) },
                    { label: "HD shots", value: String(g.high_danger_shots) },
                  ]}
                  note={notes.get(g.id) ?? null}
                />
              ))}
            </div>
          </section>

          {rows.length > 3 && (
            <section className="bd-section" aria-labelledby="board-h">
              <div className="bd-section-head">
                <h2 id="board-h" className="bd-heading">The board</h2>
                <span className="bd-label">HD shots are high-danger chances faced · tap a column to re-rank</span>
              </div>
              <Board
                key={`${sort}-${minGames}`}
                rows={rows.slice(3)}
                firstRank={4}
                columns={GOALIE_COLUMNS}
                sort={sort}
                onSort={(k) => set("sort", k, "gsax")}
                teams={teams}
                subline={(g) => `${g.games} GP · ${savePct(g.save_percentage)} · ${fixed(g.gaa, 2)} GAA`}
                label="Top goalies"
              />
            </section>
          )}
        </>
      )}
    </main>
  );
};

/** The leaderboards: every rostered skater or goalie this season, ranked on the stat asked for, the top three on cards. */
export const TopPlayersPage: FC = () => {
  const { season = "current", n, player_type } = useParams<{ season: string; n: string; player_type: PlayerType }>();
  const count = Math.max(3, Number(n) || 50);
  return (
    <div className="bd-page">
      {player_type === "goalies" ? <GoaliesPage season={season} n={count} /> : <SkatersPage season={season} n={count} />}
    </div>
  );
};

export default TopPlayersPage;
