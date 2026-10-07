import math
from predictions.predict import prop_probability

def test_over_under_half_point_lines_sum_to_one():
    expected = {"shots_on_goal": 2.8}
    over = prop_probability(expected, "player_shots_on_goal", 2.5, "Over")
    under = prop_probability(expected, "player_shots_on_goal", 2.5, "Under")
    assert math.isclose(over + under, 1.0)
    # P(X >= 3) for Poisson(2.8)
    p_le_2 = math.exp(-2.8) * (1 + 2.8 + 2.8 ** 2 / 2)
    assert math.isclose(over, 1 - p_le_2)

def test_whole_number_line_push_counts_for_neither_side():
    expected = {"saves": 25.0}
    over = prop_probability(expected, "player_total_saves", 25.0, "Over")
    under = prop_probability(expected, "player_total_saves", 25.0, "Under")
    assert over + under < 1.0

def test_unknown_market_or_missing_model_returns_none():
    assert prop_probability({"goals": 0.3}, "player_blocked_shots", 0.5, "Over") is None
    assert prop_probability({"goals": 0.3}, "player_shots_on_goal", 2.5, "Over") is None

def test_over_dispersed_stats_use_negative_binomial():
    # hits are priced with alpha 0.12: wider than Poisson, so a low line's over is less likely
    nb_over = prop_probability({"hits": 1.2}, "player_hits", 0.5, "Over")
    poisson_over = 1 - math.exp(-1.2)
    assert nb_over < poisson_over
    under = prop_probability({"hits": 1.2}, "player_hits", 0.5, "Under")
    assert math.isclose(nb_over + under, 1.0)

def test_anytime_goal_yes_is_at_least_one_goal():
    assert math.isclose(prop_probability({"goals": 0.4}, "player_goal_scorer_anytime", 0.5, "Yes"), 1 - math.exp(-0.4))
