import os
import sys
from types import SimpleNamespace as P

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from external.propline.dedupe import select_best_props


def prop(line, odds, over_under="Over", player_id=1, prop_type="player_points", book="draftkings"):
    return P(game_id=10, player_id=player_id, prop_type=prop_type, over_under=over_under, line=line, odds=odds, book=book)


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


def test_only_consensus_books_set_the_price():
    # Bovada's better price and its own line don't count while a consensus book quotes the prop
    props = [prop(0.5, -120), prop(0.5, -110, book="fanduel"), prop(0.5, 120, book="bovada"),
             prop(1.5, 200, book="bovada"), prop(1.5, 210, book="kalshi")]
    best = select_best_props(props)[0]
    assert (best.line, best.odds, best.book) == (0.5, -110, "fanduel")


def test_other_books_used_when_no_consensus_book_quotes_it():
    best = select_best_props([prop(0.5, 120, book="bovada"), prop(0.5, 130, book="novig")])[0]
    assert (best.odds, best.book) == (130, "novig")


def test_both_sides_share_the_consensus_line():
    # one-sided rungs can't pull the over onto a different line from the under
    props = [prop(2.5, -120), prop(2.5, -110, book="fanduel"), prop(0.5, -1600, book="hardrock"),
             prop(2.5, -105, over_under="Under"), prop(2.5, -110, over_under="Under", book="fanduel")]
    best = {p.over_under: (p.line, p.odds) for p in select_best_props(props)}
    assert best == {"Over": (2.5, -110), "Under": (2.5, -105)}
