import type { ReactNode } from "react";

export interface UpcomingGame {
    date: string;
    opposing_team_tricode: string;
    venue: string;
    time: Date;
    home_away: "HOME" | "AWAY";
}

export interface PlayerData {
    name: string;
    number: number | null;
    team: string;
    position: Position;
    headshotUrl: string;
    upcomingGame: UpcomingGame;
}

export interface PlayerHeaderProps extends PlayerData {
    seasonSummary: { label: string; value: number | string }[];
}

export interface PlayerUpcomingGameProps {
    upcomingGame: UpcomingGame;

}
export interface PlayerPredictionCardProps {
    label: string;
    value: number | string;
    icon: string;
    color: string;
    bgColor: string;
    subtext: ReactNode;
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

export interface PositionGroupConfig {
    key: Position;
    label: string;
    plural: string;
}

export interface PlayerCardProps {
    player: PlayerFullData;
    index: number;
}

export interface PositionGroupProps {
    label: string;
    players: PlayerFullData[];
    startIndex: number;
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
    // "odds_api": best price across books; "espn": one book's market from ESPN (e.g. hits, which the Odds API lacks)
    source: "odds_api" | "espn";
    book: string | null;
}
