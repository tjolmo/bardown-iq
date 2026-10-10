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
/** One team's line in the NHL standings; ranks as the NHL orders them (1 is first). */
export interface TeamStanding {
  conference: string;   // Eastern / Western
  division: string;     // Atlantic / Metropolitan / Central / Pacific
  gamesPlayed: number;
  wins: number;
  losses: number;
  otLosses: number;
  points: number;
  regulationWins: number;
  goalsFor: number;
  goalsAgainst: number;
  goalDifferential: number;
  streak: string | null;   // "W3", "L1", "OT2"
  last10: string | null;   // "6-3-1"
  divisionRank: number;
  conferenceRank: number;
  leagueRank: number;
  wildcardRank: number;    // 0 for a team in its division's top three
  clinch: string | null;   // x / y / z / p, or e (eliminated)
}

/** A team's next scheduled game: the opponent, this team's win chance from the model, and the edge. */
export interface TeamNextGame {
  id: number;
  opponent: Team;
  home: boolean;
  startTime: string;
  venue: string | null;
  gameState: string;
  probWin: number | null;
  moneyline: TeamMoneyline | null;
  edge: TeamGameEdge | null;
}

export interface TeamStandingsRow {
  team: Team;
  city: string;
  nickname: string;
  // null while the standings feed is unavailable
  standing: TeamStanding | null;
  nextGame: TeamNextGame | null;
}

export interface TeamStandings {
  seasonId: number | null;   // 20262027
  asOf: string | null;       // when the NHL said the standings were current
  stale: boolean;            // the feed failed and these are older than the cache
  teams: TeamStandingsRow[];
}
