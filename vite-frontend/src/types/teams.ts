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
  home: number;
  away: number;
}