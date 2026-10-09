from collections import Counter, defaultdict

from external.propline.books import CONSENSUS_BOOKS


def select_best_props(props: list) -> list:
    """Collapses the same prop offered by several bookmakers into one deliberate row per side.

    Props are grouped by (game_id, player_id, prop_type). Within a group only the consensus books count
    (books.CONSENSUS_BOOKS; the other stored books only when none of them quotes the prop), the consensus line (most
    quotes over both sides; the lower line on a tie) is chosen for both sides, so over and under are always the same
    bet, then each side's best price at that line. American odds are better for the bettor the higher they are
    (+150 > +120 > -110 > -130). A side with no quote at that line is left out. The chosen row keeps its `book`.
    """
    groups = defaultdict(list)
    for prop in props:
        groups[(prop.game_id, prop.player_id, prop.prop_type)].append(prop)

    selected = []
    for group in groups.values():
        consensus = [p for p in group if getattr(p, "book", None) in CONSENSUS_BOOKS]
        group = consensus or group
        line_counts = Counter(prop.line for prop in group)
        top = max(line_counts.values())
        consensus_line = min(line for line, count in line_counts.items() if count == top)
        sides = defaultdict(list)
        for p in group:
            if p.line == consensus_line:
                sides[p.over_under].append(p)
        selected.extend(max(side, key=lambda p: p.odds) for side in sides.values())
    return selected
