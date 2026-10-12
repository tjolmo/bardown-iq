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

// The leaderboards: a player's identity and season totals, ranked on the stat asked for
export interface TopPlayer {
    id: number;
    headshot: string | null;
    first_name: string;
    last_name: string;
    current_team_tri_code: string;
    position: Position;
    number: number | null;
    shoots_catches: "L" | "R" | "U";
    games: number;
}

export interface TopSkater extends TopPlayer {
    goals: number;
    assists: number;
    points: number;
    points_per_game: number;
    x_goals: number;
    shots_on_goal: number;
    toi_per_game: number;       // minutes
    pp_points: number;
    points_by_game: number[];   // in game order
}

export interface TopGoalie extends TopPlayer {
    shots_faced: number;
    goals_against: number;
    x_goals_against: number;
    save_percentage: number | null;
    gaa: number | null;
    gsax: number;               // goals saved above expected
    high_danger_shots: number;
}

export type SkaterSort = "points" | "goals" | "assists" | "points_per_game" | "x_goals" | "pp_points";
export type GoalieSort = "gsax" | "save_percentage" | "gaa" | "shots_faced";
export type PositionFilter = "all" | "F" | "D";

interface TopBoard {
    season: number;
    through: string | null;     // "2026-10-09", the latest game logged this season
}

export interface TopSkatersBoard extends TopBoard {
    sort: SkaterSort;
    position: PositionFilter;
    skaters: TopSkater[];
}

export interface TopGoaliesBoard extends TopBoard {
    sort: GoalieSort;
    min_games: number;
    goalies: TopGoalie[];
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
    // false for the books kept out of the consensus (Bovada, exchanges, Fliff, the pick apps)
    consensus: boolean;
    // a pick'em app (PrizePicks, Underdog, Sleeper, ...): the price is a per-pick payout multiplier
    pick_app?: boolean;
    // false when the book posts the line with no price of its own (PrizePicks): `odds` is a placeholder
    priced?: boolean;
}
