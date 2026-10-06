import os
import sys
from types import SimpleNamespace as P

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.player_matching import index_players_by_name, match_player


def player(id, first, last, position="C", team="VAN"):
    return P(id=id, first_name=first, last_name=last, position=position, current_team_tri_code=team)


def test_accent_and_punctuation_differences_match():
    idx = index_players_by_name([player(1, "Tim", "Stützle", team="OTT"), player(2, "J.T.", "Miller")])
    assert match_player(idx, "Tim", "Stutzle", "player_points")[0].id == 1
    assert match_player(idx, "JT", "Miller", "player_goals")[0].id == 2


def test_multi_word_names_match_without_splitting():
    idx = index_players_by_name([player(1, "Mary Ann", "Smith")])
    assert match_player(idx, "Mary", "Ann Smith", "player_points")[0].id == 1


def test_duplicate_skaters_are_ambiguous_not_a_crash():
    idx = index_players_by_name([player(1, "Elias", "Pettersson", "C"), player(2, "Elias", "Pettersson", "D")])
    assert match_player(idx, "Elias", "Pettersson", "player_points") == (None, "ambiguous")


def test_goalie_vs_skater_disambiguated_by_market():
    idx = index_players_by_name([player(1, "Sam", "Smith", "G"), player(2, "Sam", "Smith", "C")])
    assert match_player(idx, "Sam", "Smith", "player_total_saves")[0].id == 1
    assert match_player(idx, "Sam", "Smith", "player_points")[0].id == 2


def test_unknown_player():
    idx = index_players_by_name([player(1, "A", "B")])
    assert match_player(idx, "C", "D", "player_points") == (None, "not_found")
