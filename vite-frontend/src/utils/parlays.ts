import type { EdgePlayer } from "../types/edges";
import type { PlayerPropData } from "../types/player";
import { decimalOdds } from "./books";
import { allPrices } from "./edgePricing";
import { impliedProb } from "./playerStats";

// Parlays across games at one book. Legs in different games are treated as independent, so a parlay's chance is the
// product of its legs' model chances. Legs in the same game move together (a low-shot game helps every shots under in
// it at once) and the model has no joint chances for them, so a parlay never has two legs from one game.

/** One side the parlay can use: the player's prop at the book's price on the model's line. */
export interface Leg {
  key: string;
  player: EdgePlayer;
  prop: PlayerPropData;
  gameId: number;
  chance: number;          // the model's
  odds: number | null;     // American odds at the book; null at a line-only app (PrizePicks)
  price: number;           // decimal: the book's price, or a line-only app's break-even per pick
  edge: number;            // chance * price - 1
}

export interface Parlay {
  legs: Leg[];
  payout: number;           // the multiple of the stake paid when every leg wins
  hit: number;              // the model's chance every leg wins
  bookChance: number;       // what the payout implies (vig in, for a book's parlay)
  edge: number;             // expected return per unit staked
  tiers: [number, number][] | null;   // a flex entry's [correct picks, payout], best first
  perPick: number | null;   // an entry paid from a table: the chance each pick needs, all alike, to break even
}

export interface Pricing {
  book: string;
  legs: number;
  // a line-only app's payout table for this number of legs; absent: the book's own prices, multiplied together
  table?: Record<number, number>;
}

/** The chance of each number of wins (index) among independent legs. */
export const winCounts = (chances: number[]): number[] => {
  let dist = [1];
  for (const c of chances) {
    const next = new Array(dist.length + 1).fill(0);
    dist.forEach((p, k) => {
      next[k] += p * (1 - c);
      next[k + 1] += p * c;
    });
    dist = next;
  }
  return dist;
};

/** Expected return per unit of an entry paid from a table, for independent picks with these chances. */
export const tableEdge = (chances: number[], table: Record<number, number>): number =>
  winCounts(chances).reduce((s, p, k) => s + p * (table[k] ?? 0), 0) - 1;

/** The chance every pick needs, all alike, for the entry to break even. */
export const breakEven = (legs: number, table: Record<number, number>): number => {
  let lo = 0, hi = 1;
  for (let i = 0; i < 50; i++) {
    const mid = (lo + hi) / 2;
    if (tableEdge(new Array(legs).fill(mid), table) > 0) hi = mid;
    else lo = mid;
  }
  return hi;
};

/** Every side the book posts on the model's line: at its own price, or, for a line-only app, at the entry's
 *  break-even per pick. */
export const legsAtBook = (players: EdgePlayer[], pricing: Pricing): Leg[] => {
  const perPick = pricing.table ? 1 / breakEven(pricing.legs, pricing.table) : null;
  const legs: Leg[] = [];
  for (const player of players) {
    for (const prop of player.props) {
      if (prop.model_prob === null) continue;
      const quotes = allPrices(prop).filter((b) => b.book === pricing.book && b.line === prop.line);
      if (quotes.length === 0) continue;
      let odds: number | null = null;
      let price: number;
      if (perPick !== null) {
        price = perPick;
      } else {
        const priced = quotes.filter((b) => b.priced !== false);
        if (priced.length === 0) continue;
        odds = priced.reduce((a, b) => (decimalOdds(b.odds) > decimalOdds(a.odds) ? b : a)).odds;
        price = decimalOdds(odds);
      }
      legs.push({
        key: `${player.player_id}-${prop.prop_type}-${prop.over_under}-${prop.line}`,
        player, prop, gameId: player.game_id, chance: prop.model_prob, odds, price, edge: prop.model_prob * price - 1,
      });
    }
  }
  return legs;
};

// how many legs are combined at most: the best few per game, then the best overall
const PER_GAME = 4;
const MAX_LEGS = 40;

const price = (legs: Leg[], pricing: Pricing): Parlay => {
  const hit = legs.reduce((p, l) => p * l.chance, 1);
  if (pricing.table) {
    const top = pricing.table[legs.length] ?? 0;
    const tiers = Object.entries(pricing.table).map(([k, v]) => [Number(k), v] as [number, number]).sort((a, b) => b[0] - a[0]);
    return {
      legs, hit, payout: top, bookChance: top > 0 ? 1 / top : 1,
      edge: tableEdge(legs.map((l) => l.chance), pricing.table), tiers: tiers.length > 1 ? tiers : null,
      perPick: breakEven(legs.length, pricing.table),
    };
  }
  const payout = legs.reduce((p, l) => p * l.price, 1);
  const bookChance = legs.reduce((p, l) => p * (l.odds === null ? 1 / l.price : impliedProb(l.odds)), 1);
  return { legs, hit, payout, bookChance, edge: hit * payout - 1, tiers: null, perPick: null };
};

/** Every parlay of `pricing.legs` legs, one per game, from the legs that pass, best edge first. */
export const buildParlays = (legs: Leg[], pricing: Pricing): Parlay[] => {
  const byGame = new Map<number, Leg[]>();
  legs.forEach((l) => byGame.set(l.gameId, [...(byGame.get(l.gameId) ?? []), l]));
  const pool = [...byGame.values()]
    .flatMap((g) => g.sort((a, b) => b.edge - a.edge).slice(0, PER_GAME))
    .sort((a, b) => b.edge - a.edge)
    .slice(0, MAX_LEGS);

  const out: Parlay[] = [];
  const pick = (start: number, chosen: Leg[], games: Set<number>) => {
    if (chosen.length === pricing.legs) {
      out.push(price(chosen, pricing));
      return;
    }
    for (let i = start; i < pool.length; i++) {
      const leg = pool[i];
      if (games.has(leg.gameId)) continue;
      games.add(leg.gameId);
      pick(i + 1, [...chosen, leg], games);
      games.delete(leg.gameId);
    }
  };
  pick(0, [], new Set());
  return out.sort((a, b) => b.edge - a.edge);
};

/** The best parlays, each leg in at most `perLeg` of them, so the list isn't one strong leg with everything else. */
export const varied = (parlays: Parlay[], perLeg: number, count: number): Parlay[] => {
  const used = new Map<string, number>();
  const out: Parlay[] = [];
  for (const p of parlays) {
    if (out.length >= count) break;
    if (p.legs.some((l) => (used.get(l.key) ?? 0) >= perLeg)) continue;
    p.legs.forEach((l) => used.set(l.key, (used.get(l.key) ?? 0) + 1));
    out.push(p);
  }
  return out;
};

/** A decimal payout as American odds: 3.64 -> +264, 1.5 -> -200. */
export const decimalToAmerican = (dec: number): number =>
  dec >= 2 ? Math.round((dec - 1) * 100) : Math.round(-100 / (dec - 1));
