// GET /teams/{tricode}/lineup: the next game's lines, goalies, injuries and scratches (backend app/team_lineup.py)

export interface LineupPlayer {
    id: number;
    firstName: string | null;
    lastName: string | null;
    number: number | null;
    position: string | null;
    shoots: string | null;
    headshot: string | null;
    // LW / C / RW, LD / RD, F / D (special teams), G
    slot: string | null;
    // day_to_day players can be in the lineup; out / ir / ltir / suspended can't
    injuryStatus: string | null;
    // players coming into the lineup: straight games scratched before it
    gamesScratched?: number | null;
}

export interface LineupUnit {
    // F1-F4, D1-D3, PP1-PP2, PK1-PK2
    name: string;
    players: LineupPlayer[];
    // seconds this exact group played together last game (5 on 5 for lines and pairs)
    secondsLastGame: number;
    // of the games the projection weighs, how many it played together
    gamesTogether: number;
}

export interface LineupGoalie {
    role: "starter" | "backup";
    // confirmed / probable (ESPN), actual (once the game has started), projected
    status: string;
    player: LineupPlayer;
}

export interface LineupGame {
    id: number;
    startTime: string;
    venue: string | null;
    opponent: string;
    home: boolean;
    gameState: string;
}

export interface TeamInjury {
    // null when ESPN's listing couldn't be matched to an NHL player
    playerId: number | null;
    name: string | null;
    position: string | null;
    // out / ir / ltir / suspended / day_to_day
    status: string;
    injuryType: string | null;
    returnDate: string | null;
    comment: string | null;
    reportedAt: string | null;
    player: LineupPlayer | null;
}

export interface TeamScratch {
    player: LineupPlayer;
    // not on the injury report: the coach's call
    healthy: boolean;
    gamesScratched: number;
    gameId: number;
}

export interface TeamLineup {
    team: string;
    game: LineupGame | null;
    // "confirmed": the NHL posted the dressed players; "projected": from recent games
    status: "confirmed" | "projected";
    // games the lines were projected from, newest first
    basedOn: number[];
    forwards: LineupUnit[];
    defense: LineupUnit[];
    powerPlay: LineupUnit[];
    penaltyKill: LineupUnit[];
    goalies: LineupGoalie[];
    extras: LineupPlayer[];
    changes: { playersIn: LineupPlayer[]; playersOut: LineupPlayer[] };
    injuries: TeamInjury[];
    scratches: TeamScratch[];
    injuryReportAsOf: string | null;
    lineupsUpdatedAt: string | null;
}
