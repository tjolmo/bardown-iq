import { useMemo, type FC } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { EdgeGameCard, type EdgeRow } from "../components/edges/EdgeGameCard";
import { EdgePlayerCard } from "../components/edges/EdgePlayerCard";
import { edgeText, fullName, playerPath, SHORT_MARKETS, sideName } from "../components/edges/edgeFormat";
import { formatPropType } from "../utils/propMarkets";
import { Headshot } from "../components/rinkboard/Headshot";
import { RinkHero } from "../components/rinkboard/RinkHero";
import { useEdgeBoard } from "../hooks/useEdgeBoard";
import { useStoredState } from "../hooks/useStoredState";
import type { TeamLookup } from "../types/teams";
import { decimalOdds, formatBook, formatPrice, type OddsFormat } from "../utils/books";
import { priceSlate, slateBooks, type PricedPlayer, type PricedProp } from "../utils/edgePricing";
import { localTime, splitTeamName } from "../utils/gameStatus";
import { impliedProb, pct, POSITION_NAMES, teamOf } from "../utils/playerStats";

type View = "edge" | "game";

const MIN_EDGES = [
  { key: "0", label: "Any" },
  { key: "0.03", label: "3%+" },
  { key: "0.05", label: "5%+" },
  { key: "0.1", label: "10%+" },
];

// American odds at or above this are long shots (anytime goals for depth players, mostly)
const LONG_SHOT_ODDS = 400;

const isView = (v: unknown): v is View => v === "edge" || v === "game";
const isFormat = (v: unknown): v is OddsFormat => v === "american" || v === "decimal";
const isBookList = (v: unknown): v is string[] => Array.isArray(v) && v.every((b) => typeof b === "string");

const formatGameDate = (date: number): string => {
  const s = String(date);
  return new Date(`${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}T12:00:00`).toLocaleDateString(undefined, {
    weekday: "long", month: "long", day: "numeric",
  });
};

const betName = (p: PricedProp): string =>
  `${sideName(p.over_under)}${p.over_under.toUpperCase() === "YES" ? "" : ` ${p.line}`} ${formatPropType(p.prop_type).toLowerCase()}`;

const Pills: FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="lb-pills" role="group" aria-label={label}>
    <span className="bd-label">{label}</span>
    <div className="lb-pills-row">{children}</div>
  </div>
);

const Pill: FC<{ on: boolean; onClick: () => void; className?: string; title?: string; children: React.ReactNode }> = ({ on, onClick, className, title, children }) => (
  <button type="button" className={`pl-filter${className ? ` ${className}` : ""}`} aria-pressed={on} onClick={onClick} title={title}>
    {children}
  </button>
);

/** Centre ice: the slate's best edge at the visitor's books. */
const LeadZone: FC<{ lead: { player: PricedPlayer; prop: PricedProp } | null; teams: TeamLookup; format: OddsFormat; mine: boolean; loading: boolean }> = ({
  lead, teams, format, mine, loading,
}) => {
  if (loading) {
    return (
      <div className="ed-lead-wait" role="status">
        <strong>Pricing the slate's props</strong>
        <span className="bd-muted">The first load of the day can take up to a minute.</span>
      </div>
    );
  }
  if (!lead) {
    return <span className="bd-muted" style={{ fontSize: 13, fontWeight: 600 }}>No prop has an edge {mine ? "at your books" : "on this slate"}.</span>;
  }
  const { player, prop } = lead;
  const team = player.team ? teamOf(teams, player.team) : null;
  return (
    <div className="lb-leader">
      <Headshot player={player} size={130} className="lb-face-lead" />
      <div className="lb-leader-text">
        <span className="bd-chip bd-chip-final" style={{ alignSelf: "flex-start" }}>Best edge {mine ? "at your books" : "on the slate"}</span>
        <Link to={playerPath(player)} className="lb-name lb-name-xl">{fullName(player)}</Link>
        <span className="lb-leader-meta">
          {team && <img src={team.logoUrl} alt="" />}
          {team && <span>{team.name === team.tricode ? team.name : splitTeamName(team.name).nickname}</span>}
          {player.position && <span>· {POSITION_NAMES[player.position] ?? player.position}</span>}
          <span style={{ flexBasis: "100%" }}>{player.home ? "vs" : "@"} {player.opponent}{player.start_time && ` · ${localTime(player.start_time)}`}</span>
        </span>
        <span className="lb-leader-big">
          <span className="bd-score lb-big ed-red">{edgeText(prop.edge!)}</span>
          <span className="bd-label">Edge</span>
        </span>
        <span className="bd-muted" style={{ fontSize: 14 }}>
          <strong className="ed-ink">{betName(prop)}</strong> at <strong className="ed-ink">{formatPrice(prop.odds, format)}</strong>, {formatBook(prop.book)}.
          {prop.model_prob !== null && ` Model ${pct(prop.model_prob)}, book ${pct(impliedProb(prop.odds))}.`}
        </span>
      </div>
    </div>
  );
};

/** The edge worked through on the top bet: the model's chance times the payout, less the stake. */
const EdgeMath: FC<{ player: PricedPlayer; prop: PricedProp; format: OddsFormat; mine: boolean }> = ({ player, prop, format, mine }) => {
  const dec = decimalOdds(prop.odds);
  const chance = prop.model_prob!;
  return (
    <section className="bd-section" aria-labelledby="math-h">
      <div className="bd-section-head">
        <h2 id="math-h" className="bd-heading">How the edge is figured</h2>
        <span className="bd-label">{fullName(player)}, {betName(prop)}</span>
      </div>
      <div className="bd-card ed-math">
        <div>
          <span className="bd-label">Model's chance</span>
          <span className="bd-score">{(chance * 100).toFixed(1)}%</span>
          <p>How often the model has {player.first_name} going {betName(prop)}.</p>
        </div>
        <div>
          <span className="bd-label">× Payout per $1</span>
          <span className="bd-score">{dec.toFixed(2)}</span>
          <p>
            {format === "decimal" ? "The price" : formatPrice(prop.odds, format)} at {formatBook(prop.book)}, the best {mine ? "at your books" : "across the books"},
            returns ${dec.toFixed(2)} on a winning dollar.
          </p>
        </div>
        <div>
          <span className="bd-label">− The stake</span>
          <span className="bd-score">{(chance * dec).toFixed(3)} − 1</span>
          <p>What each dollar is worth if the model is right, less the dollar itself.</p>
        </div>
        <div>
          <span className="bd-label">= Edge</span>
          <span className="bd-score ed-red">{edgeText(prop.edge!)}</span>
          <p>Expected return per dollar. A small edge often comes from one book's price being a little better than the rest, not from the forecast.</p>
        </div>
      </div>
    </section>
  );
};

/** Players with edge: every prop side on the next slate the model prices above the best available price, on the Rink
 *  Board. The odds format and the visitor's books are kept in this browser; the filters live in the URL. */
export const EdgePlayersPage: FC = () => {
  const { data: board, teams, loading, error } = useEdgeBoard();
  const [params, setParams] = useSearchParams();
  const [view, setView] = useStoredState<View>("edges.view", "edge", isView);
  const [format, setFormat] = useStoredState<OddsFormat>("edges.oddsFormat", "american", isFormat);
  const [bookList, setBookList] = useStoredState<string[]>("edges.books", [], isBookList);

  const minParam = params.get("min") ?? "0";
  const minKey = MIN_EDGES.some((m) => m.key === minParam) ? minParam : "0";
  const minEdge = Number(minKey);
  const market = params.get("market");
  const hideLongShots = params.get("long") === "hide";
  const set = (key: string, value: string | null) =>
    setParams((p) => {
      if (value === null) p.delete(key);
      else p.set(key, value);
      return p;
    }, { replace: true });

  const books = useMemo(() => slateBooks(board?.players ?? []), [board]);
  // a remembered book that isn't on this slate doesn't filter the board down to nothing
  const myBooks = useMemo(() => new Set(bookList.filter((b) => books.some(([k]) => k === b))), [bookList, books]);
  const toggleBook = (b: string) => setBookList(myBooks.has(b) ? bookList.filter((x) => x !== b) : [...bookList, b]);

  const slate = useMemo(() => priceSlate(board?.players ?? [], myBooks), [board, myBooks]);

  const markets = useMemo(() => {
    const keys = new Set<string>();
    slate.forEach((pl) => pl.props.forEach((p) => (p.edge ?? 0) > 0 && keys.add(p.prop_type)));
    if (market) keys.add(market);
    return [...keys].sort((a, b) => formatPropType(a).localeCompare(formatPropType(b)));
  }, [slate, market]);

  const rows: EdgeRow[] = useMemo(() => {
    const passes = (p: PricedProp) =>
      p.edge !== null && p.edge > minEdge
      && (market === null || p.prop_type === market)
      && !(hideLongShots && p.odds >= LONG_SHOT_ODDS);
    return slate
      .map((player) => ({ player, edgeProps: player.props.filter(passes).sort((a, b) => b.edge! - a.edge!) }))
      .filter((r) => r.edgeProps.length > 0)
      .sort((a, b) => b.edgeProps[0].edge! - a.edgeProps[0].edge!);
  }, [slate, minEdge, market, hideLongShots]);

  const games = useMemo(() => {
    const byGame = new Map<number, EdgeRow[]>();
    rows.forEach((r) => byGame.set(r.player.game_id, [...(byGame.get(r.player.game_id) ?? []), r]));
    return [...byGame.values()];
  }, [rows]);

  // the hero and the worked example follow the books and the odds format, not the filters
  const lead = useMemo(() => {
    let best: { player: PricedPlayer; prop: PricedProp } | null = null;
    for (const player of slate) {
      for (const prop of player.props) {
        if (prop.edge !== null && prop.edge > 0 && prop.model_prob !== null && (!best || prop.edge > best.prop.edge!)) best = { player, prop };
      }
    }
    return best;
  }, [slate]);

  const mine = myBooks.size > 0;
  const gameCount = new Set(board?.players.map((p) => p.game_id)).size;
  const sideCount = rows.reduce((n, r) => n + r.edgeProps.length, 0);

  const emptyLine = () => {
    const what = [minEdge ? `clears ${minEdge * 100}%` : "has an edge", market && `in ${formatPropType(market).toLowerCase()}`, mine && "at your books"]
      .filter(Boolean).join(" ");
    return `No prop ${what}. Lower the edge, pick another market${mine ? " or add a book" : ""}.`;
  };

  return (
    <div className="bd-page">
      <main className="bd-main">
        <RinkHero
          labelledBy="edge-title"
          left={
            <>
              <span className="bd-label" style={{ alignSelf: "flex-start" }}>
                {board?.game_date
                  ? `${formatGameDate(board.game_date)} · ${gameCount} ${gameCount === 1 ? "game" : "games"}`
                  : "The next slate"}
              </span>
              <h1 id="edge-title" className="bd-display-xl">Players<br />with Edge</h1>
              <p className="bd-muted" style={{ margin: 0, maxWidth: 340 }}>
                Every prop where the model's chance, at the best price {mine ? "at your books" : "across the books"}, pays back more than the stake.
                Edge is the expected return on each dollar.
              </p>
            </>
          }
          right={error ? null : <LeadZone lead={lead} teams={teams} format={format} mine={mine} loading={loading} />}
        />

        {error ? (
          <p className="bd-empty" role="alert">The edge board didn't load. Check that the API is up, then refresh the page.</p>
        ) : loading ? null : !board?.game_date ? (
          <p className="bd-empty">No upcoming games with props yet.</p>
        ) : (
          <>
            <div className="ed-tools">
              <div className="ed-segs">
                <div className="tm-seg ed-seg" role="group" aria-label="Arrange the board">
                  <button type="button" aria-pressed={view === "edge"} onClick={() => setView("edge")}>Best edge</button>
                  <button type="button" aria-pressed={view === "game"} onClick={() => setView("game")}>By game</button>
                </div>
                <div className="tm-seg ed-seg" role="group" aria-label="Odds format">
                  <button type="button" aria-pressed={format === "american"} onClick={() => setFormat("american")}>American</button>
                  <button type="button" aria-pressed={format === "decimal"} onClick={() => setFormat("decimal")}>Decimal</button>
                </div>
              </div>
              <div className="ed-filters">
                <Pills label="Edge">
                  {MIN_EDGES.map((m) => (
                    <Pill key={m.key} on={minKey === m.key} onClick={() => set("min", m.key === "0" ? null : m.key)}>{m.label}</Pill>
                  ))}
                </Pills>
                <Pills label="Market">
                  <Pill on={market === null} onClick={() => set("market", null)}>ALL</Pill>
                  {markets.map((m) => (
                    <Pill key={m} on={market === m} onClick={() => set("market", m)}>{(SHORT_MARKETS[m] ?? formatPropType(m)).toUpperCase()}</Pill>
                  ))}
                </Pills>
                <Pill on={hideLongShots} className="ed-toggle" onClick={() => set("long", hideLongShots ? null : "hide")}>
                  <i aria-hidden="true" />HIDE {formatPrice(LONG_SHOT_ODDS, format)} AND LONGER
                </Pill>
              </div>
              <div className="ed-books">
                <Pills label="My books">
                  <Pill on={!mine} onClick={() => setBookList([])}>ALL</Pill>
                  {books.map(([b, n]) => (
                    <Pill key={b} on={myBooks.has(b)} className="ed-book" onClick={() => toggleBook(b)}
                      title={`Prices ${n} ${n === 1 ? "side" : "sides"} on this slate`}>
                      {formatBook(b)}<small>{n}</small>
                    </Pill>
                  ))}
                </Pills>
                <span className="ed-hint">
                  {mine ? "Prices and edges come only from these books, on the same line" : "Best price across the consensus books"}
                </span>
              </div>
            </div>

            <section className="bd-section" aria-labelledby="board-h">
              <div className="bd-section-head">
                <div className="ed-count-wrap">
                  <h2 id="board-h" className="bd-heading">The board</h2>
                  <div className="ed-count">
                    <span><strong>{rows.length}</strong> of {board.players_priced} priced players</span>
                    <span><strong>{sideCount}</strong> {sideCount === 1 ? "side" : "sides"} with edge</span>
                    {board.refreshing && <span>Refreshing prices in the background</span>}
                  </div>
                </div>
                <div className="ed-legend-wrap">
                  <span className="bd-note">under 3%? that's mostly line shopping</span>
                  <div className="bd-legend">
                    <span><i className="ed-lg-puck" />Model's chance</span>
                    <span><i className="ed-lg-mark" />Book's chance at that price</span>
                    <span><i className="ed-lg-chip" />3% or more</span>
                  </div>
                </div>
              </div>

              {rows.length === 0 ? (
                <p className="bd-empty">{emptyLine()}</p>
              ) : view === "game" ? (
                <div className="ed-list">
                  {games.map((g) => <EdgeGameCard key={g[0].player.game_id} rows={g} teams={teams} format={format} />)}
                </div>
              ) : (
                <div className="ed-list">
                  {rows.map((r, i) => (
                    <EdgePlayerCard key={r.player.player_id} player={r.player} edgeProps={r.edgeProps} rank={i + 1}
                      teams={teams} format={format} myBooks={myBooks} longShot={LONG_SHOT_ODDS} />
                  ))}
                </div>
              )}
            </section>

            {lead && <EdgeMath player={lead.player} prop={lead.prop} format={format} mine={mine} />}
          </>
        )}
      </main>
    </div>
  );
};

export default EdgePlayersPage;
