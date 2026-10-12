// PrizePicks pays a fixed multiple of the entry, not a price per pick, so its entries are priced from this table.
// Payouts change and can differ by state: check them in the app and edit here. Every parlay card shows the payout it
// used. 2-pick Power at 3x is current (Stokastic's 2026 guide); the 3- and 4-pick figures are from FTN Fantasy's
// older payout articles and are unverified.

export type PickemEntry = "power" | "flex";

export interface PayoutTable {
  // legs -> number of correct picks -> multiple of the entry paid
  [legs: number]: Record<number, number>;
}

export const PRIZEPICKS_PAYOUTS: Record<PickemEntry, PayoutTable> = {
  power: {
    2: { 2: 3 },
    3: { 3: 5 },
    4: { 4: 10 },
  },
  flex: {
    3: { 3: 2.25, 2: 1.25 },
    4: { 4: 5, 3: 1.5 },
  },
};

// the line-only pick'em apps priced from a payout table rather than a price per pick
export const PAYOUT_TABLE_APPS: Record<string, Record<PickemEntry, PayoutTable>> = {
  prizepicks: PRIZEPICKS_PAYOUTS,
};
