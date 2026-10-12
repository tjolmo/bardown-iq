// display names for PropLine's bookmaker keys (backend: external/propline/books.py)
const BOOK_TITLES: Record<string, string> = {
    draftkings: "DraftKings",
    fanduel: "FanDuel",
    betmgm: "BetMGM",
    fanatics: "Fanatics",
    betrivers: "BetRivers",
    hardrock: "Hard Rock",
    pinnacle: "Pinnacle",
    bovada: "Bovada",
    kalshi: "Kalshi",
    novig: "Novig",
    prophetx: "ProphetX",
    polymarket: "Polymarket",
    espnbet: "ESPN BET",
};

export const formatBook = (book: string | null | undefined): string =>
    book ? BOOK_TITLES[book] ?? book : "";

// ESPN names its provider ("Draft Kings", "ESPN BET"); PropLine keys its books ("draftkings"). One key per book lets the
// book filter treat them as the same book.
export const bookKey = (name: string): string => name.toLowerCase().replace(/[^a-z0-9]/g, "");

export type OddsFormat = "american" | "decimal";

/** What a winning unit returns, stake included: +144 -> 2.44, -113 -> 1.885. */
export const decimalOdds = (odds: number): number => (odds > 0 ? 1 + odds / 100 : 1 + 100 / -odds);

/** "+144" / "−113", or "2.44" / "1.88". */
export const formatPrice = (odds: number, format: OddsFormat): string =>
    format === "decimal" ? decimalOdds(odds).toFixed(2) : odds > 0 ? `+${odds}` : `−${Math.abs(odds)}`;
