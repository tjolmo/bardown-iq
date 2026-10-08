import type { PlayerPropData, Position } from "./player";

export interface EdgePlayer {
    player_id: number;
    first_name: string;
    last_name: string;
    headshot: string | null;
    position: Position | null;
    team: string | null;
    opponent: string;
    home: boolean;
    game_id: number;
    start_time: string | null;
    // goalies: confirmed / probable / projected starter (saves props assume he starts)
    starter_status: string | null;
    best_edge: number;
    // every priced prop of the player's game, best edge first
    props: PlayerPropData[];
}

export interface EdgeBoard {
    game_date: number | null;
    built_at: string;
    players_priced: number;
    // this copy is stale and the server is rebuilding it
    refreshing: boolean;
    players: EdgePlayer[];
}
