from collections import Counter, defaultdict


def select_best_props(props: list) -> list:
    """Collapses the same prop offered by several bookmakers into one deliberate row.

    Props are grouped by (game_id, player_id, prop_type, over_under). Within a group the
    consensus line (most common; the lower line on a tie) is chosen, then the best price
    at that line. American odds are better for the bettor the higher they are
    (+150 > +120 > -110 > -130).
    """
    groups = defaultdict(list)
    for prop in props:
        groups[(prop.game_id, prop.player_id, prop.prop_type, prop.over_under)].append(prop)

    selected = []
    for group in groups.values():
        line_counts = Counter(prop.line for prop in group)
        top = max(line_counts.values())
        consensus_line = min(line for line, count in line_counts.items() if count == top)
        selected.append(max((p for p in group if p.line == consensus_line), key=lambda p: p.odds))
    return selected
