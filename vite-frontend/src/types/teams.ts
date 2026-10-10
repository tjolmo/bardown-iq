export interface Team {
  tricode: string;
  name: string;
  logoUrl: string;
}

// tricode -> team, for names and logos
export type TeamLookup = Record<string, Team>;

export interface PredictedScore {
  away: number;
  home: number;
}

export interface TeamScheduledGame {
  id: number;
  date: string;
  time: string;
  venue: string;
  awayTeam: Team;
  homeTeam: Team;
  awayScore: number | null;
  homeScore: number | null;
  gameState: string | null;
  predictions?: TeamGamePrediction;
  moneyline?: TeamMoneyline;
  isNextGame?: boolean;
  // today's games once started: period and clock from NHL's score feed
  live?: TeamGameLive | null;
  // the side the model likes against the moneyline
  edge?: TeamGameEdge | null;
}

export interface TeamGameLive {
  period: number | null;
  periodType: "REG" | "OT" | "SO" | string | null;
  // of the period, or of the intermission when inIntermission (counted down to when the server answered)
  secondsRemaining: number | null;
  timeRemaining: string | null;
  inIntermission: boolean;
  clockRunning: boolean;
  // when the feed was polled: the game clock is as of then
  asOf: string;
}

export interface TeamGameEdge {
  tri_code: string;
  side: "home" | "away";
  // model win probability minus the no-vig moneyline probability, in percentage points
  points: number;
}

export interface SearchTeamResult {
  name: string;
  tricode: string;
  logoUrl: string | null;
}

export interface TeamPredictionSide {
  tri_code: string;
  prob_win: number | null;
}

export interface TeamGamePrediction {
  home: TeamPredictionSide;
  away: TeamPredictionSide;
}

export interface TeamMoneyline {
  // median price of the consensus books (PropLine), or NHL's partner feed when PropLine has none
  home: number;
  away: number;
  // best price per side among the consensus books, and which book
  best_home?: number | null;
  best_home_book?: string | null;
  best_away?: number | null;
  best_away_book?: string | null;
  n_books?: number | null;
  source?: "propline" | "nhl";
}