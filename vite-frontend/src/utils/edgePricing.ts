import type { EdgePlayer } from "../types/edges";
import type { PlayerPropData, PropBookPrice } from "../types/player";
import { bookKey, decimalOdds } from "./books";

/** A prop side as the visitor can bet it: `odds`/`book`/`edge` are the best price at their books, and `prices` is every
 *  book's price for the side (keyed by bookKey), the shown one included. */
export interface PricedProp extends PlayerPropData {
  book: string;
  prices: PropBookPrice[];
}

export interface PricedPlayer extends Omit<EdgePlayer, "props"> {
  props: PricedProp[];
}

/** Every price for the side: the shown best (consensus) price, then the other books, some at other lines. */
export const allPrices = (p: PlayerPropData): PropBookPrice[] => [
  { book: bookKey(p.book ?? "espn"), odds: p.odds, line: p.line, consensus: true },
  ...(p.other_books ?? []).map((b) => ({ ...b, book: bookKey(b.book) })),
];

/** The side at the best price among `books` on its own line (the model's chance is for that line), with the edge at that
 *  price. Every book (an empty set) keeps the server's consensus price. Null when none of the books has the side. */
export const priceAtBooks = (p: PlayerPropData, books: ReadonlySet<string>): PricedProp | null => {
  const prices = allPrices(p);
  if (books.size === 0) return { ...p, book: prices[0].book, prices };
  const best = prices
    .filter((b) => b.line === p.line && books.has(b.book) && b.priced !== false)
    .reduce<PropBookPrice | null>((a, b) => (a === null || decimalOdds(b.odds) > decimalOdds(a.odds) ? b : a), null);
  if (best === null) return null;
  const edge = p.model_prob === null ? null : p.model_prob * decimalOdds(best.odds) - 1;
  return { ...p, odds: best.odds, book: best.book, edge, prices };
};

export const priceSlate = (players: EdgePlayer[], books: ReadonlySet<string>): PricedPlayer[] =>
  players.map((pl) => ({
    ...pl,
    props: pl.props.map((p) => priceAtBooks(p, books)).filter((p): p is PricedProp => p !== null),
  }));

/** Each book on the slate and how many prop sides it prices, most first. A book that only posts lines (PrizePicks)
 *  can't be bet at a price, so it isn't one. */
export const slateBooks = (players: EdgePlayer[]): [string, number][] => {
  const counts = new Map<string, number>();
  players.forEach((pl) => pl.props.forEach((p) =>
    new Set(allPrices(p).filter((b) => b.priced !== false).map((b) => b.book))
      .forEach((b) => counts.set(b, (counts.get(b) ?? 0) + 1))));
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
};
