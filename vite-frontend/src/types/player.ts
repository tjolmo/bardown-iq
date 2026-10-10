export interface UpcomingGame {
    date: string | null;
    opposing_team_tricode: string | null;
    venue: string | null;
    time: string | null;        // ISO puck drop
    home_away: "HOME" | "AWAY" | null;
}

export interface PlayerData {
    name: string;
    number: number | null;
    team: string;
    position: Position;
    headshotUrl: string;
}

export interface PlayerFullData {
    id: number;
    headshot: string;
    first_name: string;
    last_name: string;
    current_team_tri_code: string | null;
    position: Position;
    number: number | null;
    shoots_catches: "L" | "R" | "U";
    last_updated: string;
    game_log_last_updated: string | null;
}

export type Position = "C" | "L" | "R" | "D" | "G" | "U";

export interface PlayerCardProps {
    player: PlayerFullData;
    index: number;
}

export interface SearchPlayerResult {
    id: number;
    first_name: string;
    last_name: string;
    headshot: string | null;
    current_team_tri_code: string | null;
    position: Position | null;
}

export interface PlayerPropData {
    game_id: number;
    player_id: number;
    prop_type: string;
    over_under: string;
    line: number;
    odds: number;
    // the model's chance this side wins and its expected return per unit at these odds (null until models are trained)
    model_prob: number | null;
    edge: number | null;
    // "propline": best price across the consensus books (book = the book with it); "espn": one book's market from
    // ESPN (e.g. hits, which PropLine lacks)
    source: "propline" | "espn";
    book: string | null;
    // every other book's price for this side, best first (PropLine rows only)
    other_books?: PropBookPrice[];
}

export interface PropBookPrice {
    book: string;
    odds: number;
    line: number;
    // false for the books kept out of the consensus (Bovada, exchanges)
    consensus: boolean;
}
