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
};

export const formatBook = (book: string | null | undefined): string =>
    book ? BOOK_TITLES[book] ?? book : "";

export const formatOdds = (odds: number): string =>
    odds > 0 ? `+${odds}` : `${odds}`;
