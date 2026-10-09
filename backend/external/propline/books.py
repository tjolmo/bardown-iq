"""Which PropLine books and markets are fetched, and how they map onto the market keys the rest of the app uses.

The app's prop keys are the Odds API's market keys (player_points, player_total_saves, ...): the props table,
prop_probability, the prediction log and the ESPN fallback all use them, so PropLine's keys are translated on the
way in and nothing downstream changes.
"""
# US books you can bet at plus Pinnacle (the sharpest line). The best price shown on the site and the prediction
# log's consensus come from these. Hard Rock posts the fullest NHL O/U board (blocked shots, PP points) of them.
CONSENSUS_BOOKS = ("draftkings", "fanduel", "betmgm", "fanatics", "betrivers", "hardrock", "pinnacle")
# stored and listed under "other books", but kept out of the consensus: Bovada is offshore (the widest prop board),
# the exchanges quote takeable asks rather than a book's vigged two-way price. DFS apps (PrizePicks, Underdog) are
# not fetched at all: their prices are payout tiers, not odds.
EXTRA_BOOKS = ("bovada", "kalshi", "novig", "prophetx", "polymarket")
BOOKMAKERS = CONSENSUS_BOOKS + EXTRA_BOOKS

BOOK_TITLES = {"draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM", "fanatics": "Fanatics",
               "betrivers": "BetRivers", "hardrock": "Hard Rock", "pinnacle": "Pinnacle", "bovada": "Bovada", "kalshi": "Kalshi",
               "novig": "Novig", "prophetx": "ProphetX", "polymarket": "Polymarket"}

# PropLine market key -> app market key. PropLine's docs only list player_goals, player_shots_on_goal, goalie_saves
# and player_blocked_shots for NHL, but events list the rest too (checked live Oct 2026); only markets an event lists
# are requested (client.event_markets). Hits come mostly from DFS apps, so ESPN still fills most of them.
PROP_MARKETS = {
    "player_points": "player_points",
    "player_assists": "player_assists",
    "player_goals": "player_goals",
    "player_shots_on_goal": "player_shots_on_goal",
    "player_blocked_shots": "player_blocked_shots",
    "player_power_play_points": "player_power_play_points",
    "player_hits": "player_hits",
    "goalie_saves": "player_total_saves",
    "player_total_saves": "player_total_saves",
}
# "1+" milestone rungs are the same bet as over/under 0.5. Books post them as their own keys (player_points_1plus,
# "Yes" outcomes) or as "1+ Assists" outcomes under the base key with line_type "milestone". Higher rungs are
# alternate lines and are skipped, like the alternates of the over/under markets.
MILESTONE_MARKETS = {f"{k}_1plus": v for k, v in PROP_MARKETS.items() if k.startswith("player_")}
# only where the main line is 0.5: a "1+ shots on goal" rung (-1600) is not the shots market, whose line is 2.5
RUNG_MARKETS = {"player_goals", "player_assists", "player_points", "player_power_play_points"}

GAME_MARKETS = ("h2h", "spreads", "totals")


def app_prop_key(propline_key: str) -> tuple[str | None, bool]:
    """(app market key, is a 1+ milestone) for a PropLine market key; (None, False) for markets the app doesn't use."""
    if propline_key in PROP_MARKETS:
        return PROP_MARKETS[propline_key], False
    if propline_key in MILESTONE_MARKETS:
        return MILESTONE_MARKETS[propline_key], True
    return None, False


def book_title(key: str | None) -> str | None:
    return BOOK_TITLES.get(key, key) if key else None
