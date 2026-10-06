import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.name_matching import normalize_name


def test_montreal_accent_matches_odds_api_name():
    assert normalize_name("Montréal Canadiens") == normalize_name("Montreal Canadiens") == "montreal canadiens"


def test_punctuation_and_case():
    assert normalize_name("St. Louis Blues") == normalize_name("st louis blues")
    assert normalize_name("  Utah   Mammoth ") == "utah mammoth"


def test_player_names():
    assert normalize_name("Tim Stützle") == normalize_name("Tim Stutzle")
    assert normalize_name("J.T. Miller") == "jt miller"
    assert normalize_name("Jean-Gabriel Pageau") == "jean gabriel pageau"
