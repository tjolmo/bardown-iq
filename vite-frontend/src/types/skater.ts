import type { PlayerData, PlayerPropData, UpcomingGame } from "./player";
import type { TeamLookup } from "./teams";

// the model's numbers for the next game: expected counts, and the chance of at least one for goals/assists/points
export interface SkaterGamePredictions {
  goals: number;
  assists: number;
  points: number;
  prob_goal?: number | null;
  prob_assist?: number | null;
  prob_point?: number | null;
  shots_on_goal?: number | null;
  hits?: number | null;
  blocked_shots?: number | null;
  pp_points?: number | null;
}

/** One game of a skater's log (backend SkaterGameOut). */
export interface SkaterGame {
  game_id: number;
  date: string;               // ISO date
  opposing_team_tricode: string;
  home_away: "HOME" | "AWAY" | null;
  toi: number;                // seconds
  goals: number;
  primary_assists: number;
  secondary_assists: number;
  assists: number;
  points: number;
  // null on games logged before these were scraped
  shots_on_goal: number | null;
  hits: number | null;
  blocked_shots: number | null;
  pp_points: number | null;
  pp_toi: number | null;      // 5-on-4 seconds
  x_goals: number;
  shot_attempts: number;
  high_danger_shots: number;
  on_ice_x_goals_percentage: number;
  game_score: number;
  // model stat -> what the model expected before puck drop (empty when it wasn't logged)
  expected: Record<string, number>;
}

export interface SkaterData extends PlayerData {
  upcomingGame: UpcomingGame | null;
  predictions: SkaterGamePredictions | null;
  season: SkaterGame[];       // this season, oldest first
  recent: SkaterGame[];       // the last five, across seasons, oldest first
  props: PlayerPropData[];
  teams: TeamLookup;
}
