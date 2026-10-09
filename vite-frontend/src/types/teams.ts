export interface Team {
  tricode: string;
  name: string;
  logoUrl: string;
}

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