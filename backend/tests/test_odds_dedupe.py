import os
import sys
from types import SimpleNamespace as P

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from external.odds_api.dedupe import select_best_props


def prop(line, odds, over_under="Over", player_id=1, prop_type="player_points"):
    return P(game_id=10, player_id=player_id, prop_type=prop_type, over_under=over_under, line=line, odds=odds)


def test_consensus_line_then_best_price():
    props = [prop(0.5, -130), prop(0.5, -110), prop(1.5, 250)]
    assert [(p.line, p.odds) for p in select_best_props(props)] == [(0.5, -110)]


def test_positive_odds_beat_negative_and_higher_positive_wins():
    props = [prop(0.5, -105), prop(0.5, 120), prop(0.5, 150)]
    assert select_best_props(props)[0].odds == 150


def test_line_tie_picks_lower_line():
    props = [prop(1.5, 200), prop(0.5, -120)]
    assert select_best_props(props)[0].line == 0.5


def test_over_and_under_and_players_kept_separate():
    props = [prop(0.5, -110), prop(0.5, -110, over_under="Under"), prop(0.5, -110, player_id=2)]
    assert len(select_best_props(props)) == 3
