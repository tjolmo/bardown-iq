from collections import defaultdict
from typing import Iterable

from app.name_matching import normalize_name

GOALIE_PROP_TYPES = {"player_total_saves"}


def index_players_by_name(players: Iterable) -> dict[str, list]:
    """Groups players by normalized 'first last' so lookups ignore accents/punctuation/case."""
    index = defaultdict(list)
    for player in players:
        index[normalize_name(f"{player.first_name} {player.last_name}")].append(player)
    return index


def match_player(index: dict[str, list], first_name: str, last_name: str, prop_type: str):
    """Returns (player, reason). player is None when there is no match or the match is ambiguous.

    Save props belong to goalies and every other market to skaters, which separates most
    same-name players. If several remain (e.g. two skaters with the same name) we skip the
    prop rather than guess and attach odds to the wrong player.
    """
    candidates = index.get(normalize_name(f"{first_name} {last_name}"), [])
    wants_goalie = prop_type in GOALIE_PROP_TYPES
    candidates = [p for p in candidates if (p.position == "G") == wants_goalie]
    if len(candidates) == 1:
        return candidates[0], None
    if not candidates:
        return None, "not_found"
    return None, "ambiguous"
