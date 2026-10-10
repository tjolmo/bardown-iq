import { apiGet } from "./client";
import type { Team, TeamScheduledGame, SearchTeamResult } from "../types/teams";
import type { PlayerFullData } from "../types/player";
import type { TeamLineup } from "../types/lineup";

export const getTeams = () =>
    apiGet<Team[]>("/teams/all");

export const getTeamNextFiveGames = (tricode: string, offset: number = 0) =>
    apiGet<TeamScheduledGame[]>(`/teams/${tricode}/next_5/${offset}`);

export const getTeamCurrentRoster = (tricode: string) =>
    apiGet<PlayerFullData[]>(`/teams/${tricode}/current_roster`);

export const getSearchTeam = (query: string, limit: number = 5) =>
    apiGet<SearchTeamResult[]>(`/teams/search?q=${encodeURIComponent(query)}&limit=${limit}`);
export const getTeamLineup = (tricode: string) =>
    apiGet<TeamLineup>(`/teams/${tricode}/lineup`);
