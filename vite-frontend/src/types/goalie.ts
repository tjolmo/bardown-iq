import type { PlayerData, PlayerPropData, UpcomingGame } from "./player";
import type { TeamLookup } from "./teams";

// the model's numbers for the next game, assuming the goalie starts it
export interface GoalieGamePredictions {
  saves: number;
  goals_against: number;
  shots_against?: number | null;
  save_percentage?: number | null;
  // whether the goalie is the team's expected starter, and how sure that is (confirmed / probable / projected)
  starting?: boolean | null;
  starter_status?: string | null;
}

/** One game of a goalie's log (backend GoalieGameOut). */
export interface GoalieGame {
  game_id: number;
  date: string;               // ISO date
  opposing_team_tricode: string;
  home_away: "HOME" | "AWAY" | null;
  toi: number;                // seconds
  shots_against: number;      // shots on goal faced, goals included
  saves: number;
  goals_against: number;
  x_goals_against: number;
  high_danger_shots: number;
  high_danger_x_goals: number;
  rebounds: number;
  x_rebounds: number;
  // model stat (saves, sog, goals_against) -> what the model expected before puck drop
  expected: Record<string, number>;
}

export interface GoalieData extends PlayerData {
  upcomingGame: UpcomingGame | null;
  predictions: GoalieGamePredictions | null;
  season: GoalieGame[];
  recent: GoalieGame[];
  props: PlayerPropData[];
  teams: TeamLookup;
}
