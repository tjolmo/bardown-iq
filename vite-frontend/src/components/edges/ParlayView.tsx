import { useMemo, useState, type FC, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { PAYOUT_TABLE_APPS, type PickemEntry } from "../../data/pickemPayouts";
import type { EdgePlayer } from "../../types/edges";
import type { TeamLookup } from "../../types/teams";
import { formatBook, formatPrice, type OddsFormat } from "../../utils/books";
import { allPrices } from "../../utils/edgePricing";
import { breakEven, buildParlays, decimalToAmerican, legsAtBook, varied, type Leg, type Parlay, type Pricing } from "../../utils/parlays";
import { pct } from "../../utils/playerStats";
import { formatPropType } from "../../utils/propMarkets";
import { Headshot } from "../rinkboard/Headshot";
import { TeamChip } from "../rinkboard/TeamChip";
import { edgeChipClass, edgeText, isYes, SHORT_MARKETS, sideName } from "./edgeFormat";

type Kind = "book" | "pickem";

const LEG_COUNTS = [2, 3, 4];
const MIN_LEG_EDGES = [0, 0.02, 0.03, 0.05];
// American odds; null = no cap
const MAX_LEG_ODDS: (number | null)[] = [150, 300, 500, null];
const MIN_HITS = [0.05, 0.1, 0.2, 0.33];
// each leg shows up in at most this many of the listed parlays
const PER_LEG = 3;
const PAGE = 10;

interface Props {
  players: EdgePlayer[];
  teams: TeamLookup;
  format: OddsFormat;
  myBooks: ReadonlySet<string>;
  gameCount: number;
}

interface BookInfo {
  key: string;
  pickApp: boolean;
  sides: number;
}

/** Every book on the slate, whether it's a pick'em app, and how many sides it posts on the model's line. */
const slateBooks = (players: EdgePlayer[]): BookInfo[] => {
  const books = new Map<string, BookInfo>();
  players.forEach((pl) => pl.props.forEach((p) => {
    if (p.model_prob === null) return;
    const seen = new Set<string>();
    allPrices(p).filter((b) => b.line === p.line).forEach((b) => {
      if (seen.has(b.book)) return;
      seen.add(b.book);
      const info = books.get(b.book) ?? { key: b.book, pickApp: !!b.pick_app, sides: 0 };
      info.sides += 1;
      books.set(b.book, info);
    });
  }));
  return [...books.values()].sort((a, b) => b.sides - a.sides);
};

const Pills: FC<{ label: string; children: ReactNode }> = ({ label, children }) => (
  <div className="lb-pills" role="group" aria-label={label}>
    <span className="bd-label">{label}</span>
    <div className="lb-pills-row">{children}</div>
  </div>
);

const Pill: FC<{ on: boolean; onClick: () => void; children: ReactNode }> = ({ on, onClick, children }) => (
  <button type="button" className="pl-filter" aria-pressed={on} onClick={onClick}>{children}</button>
);

const payoutText = (payout: number, fixed: boolean, format: OddsFormat): string =>
  fixed ? `${payout}×` : format === "decimal" ? payout.toFixed(2) : formatPrice(decimalToAmerican(payout), "american");

const betText = (leg: Leg): string =>
  `${sideName(leg.prop.over_under)}${isYes(leg.prop.over_under) ? "" : ` ${leg.prop.line}`} ${SHORT_MARKETS[leg.prop.prop_type] ?? formatPropType(leg.prop.prop_type)}`;

const ParlayCard: FC<{ parlay: Parlay; rank: number; teams: TeamLookup; format: OddsFormat; fixed: boolean }> = ({ parlay, rank, teams, format, fixed }) => {
  const odds = Math.max(1, Math.round(1 / parlay.hit));
  return (
    <article className="bd-card ed-parlay">
      <span className="bd-note-tag">hits about 1 in {odds}</span>
      <div className="ed-parlay-head">
        <span className="ed-rank">{rank}</span>
        <div className="ed-parlay-sum">
          <div>
            <span className="bd-label">{fixed ? "Pays" : "Price"}</span>
            <strong>{payoutText(parlay.payout, fixed, format)}</strong>
          </div>
          <div>
            <span className="bd-label">Model hits</span>
            <strong>{pct(parlay.hit)}</strong>
          </div>
          {parlay.perPick !== null ? (
            <div>
              <span className="bd-label">Each pick needs</span>
              <strong>{pct(parlay.perPick)}</strong>
            </div>
          ) : (
            <div>
              <span className="bd-label">Book's chance</span>
              <strong>{pct(parlay.bookChance)}</strong>
            </div>
          )}
        </div>
        <div className="ed-best">
          <span className="bd-score">{edgeText(parlay.edge)}</span>
          <span className="bd-label">Edge</span>
        </div>
      </div>
      <ul className="ed-legs">
        {parlay.legs.map((leg) => (
          <li className="ed-leg" key={leg.key}>
            <Headshot player={leg.player} size={40} />
            <div className="ed-who">
              <Link to={`/${leg.player.position === "G" ? "goalie" : "player"}/${leg.player.player_id}`} className="lb-name">
                {leg.player.first_name} {leg.player.last_name}
              </Link>
              <span className="lb-chips">
                {leg.player.team && <TeamChip tricode={leg.player.team} teams={teams} />}
                <span className="lb-chip">{leg.player.home ? "vs" : "@"} {leg.player.opponent}</span>
              </span>
            </div>
            <span className="ed-leg-bet">{betText(leg)}</span>
            <span className="ed-leg-price">{leg.odds !== null && formatPrice(leg.odds, format)}</span>
            <span className="ed-leg-model"><strong>{pct(leg.chance)}</strong> model</span>
            <span className={edgeChipClass(leg.edge)}>{edgeText(leg.edge)}</span>
          </li>
        ))}
      </ul>
      {parlay.tiers && (
        <div className="ed-foot">
          <span>Flex pays {parlay.tiers.map(([k, v]) => `${v}× on ${k} of ${parlay.legs.length}`).join(", ")}; the edge counts every tier</span>
        </div>
      )}
    </article>
  );
};

/** Parlays across games at one book: legs from different games multiplied together, or a pick'em entry priced from
 *  the app's payout table, best edge first with a floor on how often they hit. */
export const ParlayView: FC<Props> = ({ players, teams, format, myBooks, gameCount }) => {
  const books = useMemo(() => slateBooks(players), [players]);
  const [kind, setKind] = useState<Kind>("book");
  const [chosen, setChosen] = useState<string | null>(null);
  const [entry, setEntry] = useState<PickemEntry>("power");
  const [legCount, setLegCount] = useState(2);
  const [minEdge, setMinEdge] = useState(0.03);
  const [maxOdds, setMaxOdds] = useState<number | null>(300);
  const [minHit, setMinHit] = useState(0.1);
  const [shown, setShown] = useState(PAGE);

  // the book, the leg count the app allows, the legs at the book and every parlay of them: the costly part, so only
  // when a setting that changes them does
  const { choices, book, tables, legChoices, legs, table, usable, games, all } = useMemo(() => {
    const choices = books.filter((b) => b.pickApp === (kind === "pickem"));
    // the visitor's own book first, else the one posting the most sides
    const book = choices.find((b) => b.key === chosen)?.key
      ?? choices.find((b) => myBooks.has(b.key))?.key
      ?? choices[0]?.key
      ?? null;
    const tables = book ? PAYOUT_TABLE_APPS[book] : undefined;
    const legChoices = tables ? LEG_COUNTS.filter((n) => tables[entry][n]) : LEG_COUNTS;
    const legs = legChoices.includes(legCount) ? legCount : legChoices[0];
    const table = tables?.[entry][legs];
    if (!book) return { choices, book, tables, legChoices, legs, table, usable: [] as Leg[], games: 0, all: [] as Parlay[] };
    const pricing: Pricing = { book, legs, table };
    const usable = legsAtBook(players, pricing).filter((l) =>
      l.edge >= minEdge && (table !== undefined || maxOdds === null || l.odds === null || l.odds <= maxOdds));
    const games = new Set(usable.map((l) => l.gameId)).size;
    return { choices, book, tables, legChoices, legs, table, usable, games, all: games >= legs ? buildParlays(usable, pricing) : [] };
  }, [players, books, myBooks, kind, chosen, entry, legCount, minEdge, maxOdds]);
  const fixed = table !== undefined;
  const passing = all.filter((p) => p.hit >= minHit && p.edge > 0);
  const list = varied(passing, PER_LEG, shown);
  const more = varied(passing, PER_LEG, shown + 1).length > list.length;

  const reset = () => setShown(PAGE);
  const where = book ? formatBook(book) : "this book";

  const empty = (): string => {
    if (gameCount < 2) {
      return "This slate is one game, so there's no parlay across games. Same-game parlays aren't built yet: the model prices each leg on its own, and legs in one game move together.";
    }
    if (!book) return kind === "pickem" ? "No pick'em app has posted lines for this slate yet." : "No book has posted props for this slate yet.";
    if (games < legs) {
      return `Only ${games} ${games === 1 ? "game has" : "games have"} a leg that clears these filters at ${where}. Lower the minimum edge, raise the price cap or pick fewer legs.`;
    }
    if (passing.length === 0) {
      return `No ${legs}-leg ${fixed ? "entry" : "parlay"} at ${where} has an edge and hits at least ${pct(minHit)} of the time. Lower the hit floor or the minimum leg edge.`;
    }
    return "";
  };

  return (
    <section className="bd-section" aria-labelledby="parlay-h">
      <div className="ed-tools ed-parlay-tools">
        <div className="tm-seg ed-seg" role="group" aria-label="Parlay type">
          <button type="button" aria-pressed={kind === "book"} onClick={() => { setKind("book"); reset(); }}>Sportsbook parlay</button>
          <button type="button" aria-pressed={kind === "pickem"} onClick={() => { setKind("pickem"); reset(); }}>Pick'em entry</button>
        </div>
        <div className="ed-filters">
          <Pills label={kind === "pickem" ? "App" : "Book"}>
            {choices.map((b) => (
              <Pill key={b.key} on={b.key === book} onClick={() => { setChosen(b.key); reset(); }}>{formatBook(b.key)}</Pill>
            ))}
          </Pills>
          {tables && (
            <div className="tm-seg ed-seg" role="group" aria-label="Entry type">
              <button type="button" aria-pressed={entry === "power"} onClick={() => { setEntry("power"); reset(); }}>Power</button>
              <button type="button" aria-pressed={entry === "flex"} onClick={() => { setEntry("flex"); reset(); }}>Flex</button>
            </div>
          )}
        </div>
        <div className="ed-filters ed-books">
          <Pills label="Legs">
            {legChoices.map((n) => <Pill key={n} on={n === legs} onClick={() => { setLegCount(n); reset(); }}>{n}</Pill>)}
          </Pills>
          <Pills label={fixed ? "Edge per pick" : "Leg edge"}>
            {MIN_LEG_EDGES.map((m) => <Pill key={m} on={m === minEdge} onClick={() => { setMinEdge(m); reset(); }}>{m === 0 ? "ANY" : `${m * 100}%+`}</Pill>)}
          </Pills>
          {!fixed && (
            <Pills label="Leg price up to">
              {MAX_LEG_ODDS.map((m) => (
                <Pill key={m ?? "any"} on={m === maxOdds} onClick={() => { setMaxOdds(m); reset(); }}>
                  {m === null ? "ANY" : formatPrice(m, format)}
                </Pill>
              ))}
            </Pills>
          )}
          <Pills label="Hits at least">
            {MIN_HITS.map((m) => <Pill key={m} on={m === minHit} onClick={() => { setMinHit(m); reset(); }}>{pct(m)}</Pill>)}
          </Pills>
        </div>
      </div>

      <div className="bd-section-head">
        <div className="ed-count-wrap">
          <h2 id="parlay-h" className="bd-heading">{fixed ? "Pick'em entries" : "Parlays"}</h2>
          <div className="ed-count">
            <span><strong>{passing.length}</strong> with an edge at {where}</span>
            <span><strong>{usable.length}</strong> {usable.length === 1 ? "leg" : "legs"} across {games} {games === 1 ? "game" : "games"}</span>
          </div>
        </div>
        <span className="ed-hint ed-parlay-hint">
          {fixed && table
            ? `${formatBook(book)} ${entry} ${legs}-pick pays ${Object.entries(table).sort((a, b) => Number(b[0]) - Number(a[0])).map(([k, v]) => `${v}× on ${k}`).join(", ")}: each pick needs ${pct(breakEven(legs, table))} to break even. Check the payouts in the app.`
            : `One leg per game, priced at ${where}. Each leg appears in at most ${PER_LEG} parlays.`}
        </span>
      </div>

      {list.length === 0 ? (
        <p className="bd-empty">{empty()}</p>
      ) : (
        <>
          <div className="ed-list">
            {list.map((p, i) => (
              <ParlayCard key={p.legs.map((l) => l.key).join("|")} parlay={p} rank={i + 1} teams={teams} format={format} fixed={fixed} />
            ))}
          </div>
          {more && (
            <div className="lb-board-foot">
              <span className="bd-muted" style={{ fontSize: 13 }}>Showing {list.length}</span>
              <button type="button" className="bd-btn" onClick={() => setShown((n) => n + PAGE)}>Show more</button>
            </div>
          )}
        </>
      )}
    </section>
  );
};
