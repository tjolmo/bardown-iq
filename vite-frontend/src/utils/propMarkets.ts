/** The market's name from PropLine's key: "player_shots_on_goal" -> "Shots on Goal". */
export const formatPropType = (prop_type: string): string => {
    const map: Record<string, string> = {
        "player_goals": "Goals",
        "player_assists": "Assists",
        "player_points": "Points",
        "player_total_saves": "Saves",
        "player_shots_on_goal": "Shots on Goal",
        "player_blocked_shots": "Blocked Shots",
        "player_hits": "Hits",
        "player_power_play_points": "Power Play Points",
        "player_goal_scorer_anytime": "Anytime Goal",
    };
    return map[prop_type] || prop_type;
}
