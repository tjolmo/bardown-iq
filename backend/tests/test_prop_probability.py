import math
import pytest
from predictions.predict import prop_probability

@pytest.fixture(autouse=True)
def no_trained_bundles(tmp_path, monkeypatch):
    # dispersion comes from the trained bundles; keep the tests independent of whatever models/ holds
    from predictions import predict
    monkeypatch.setattr(predict, "SKATER_BUNDLE", tmp_path / "none_skater.joblib")
    monkeypatch.setattr(predict, "GOALIE_BUNDLE", tmp_path / "none_goalie.joblib")

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
    # a positive alpha is wider than Poisson, so a low line's over is less likely
    nb_over = prop_probability({"hits": 1.2}, "player_hits", 0.5, "Over", {"hits": 0.12})
    poisson_over = 1 - math.exp(-1.2)
    assert nb_over < poisson_over
    under = prop_probability({"hits": 1.2}, "player_hits", 0.5, "Under", {"hits": 0.12})
    assert math.isclose(nb_over + under, 1.0)
    # alpha 0 (fitted as Poisson) prices as Poisson
    assert math.isclose(prop_probability({"hits": 1.2}, "player_hits", 0.5, "Over", {"hits": 0.0}), poisson_over)

def test_dispersion_comes_from_the_bundles_with_config_fallback(tmp_path, monkeypatch):
    import joblib
    from predictions import predict
    from predictions.config import PROP_DISPERSION
    skater, goalie = tmp_path / "skater.joblib", tmp_path / "goalie.joblib"
    monkeypatch.setattr(predict, "SKATER_BUNDLE", skater)
    monkeypatch.setattr(predict, "GOALIE_BUNDLE", goalie)
    # no bundles yet: config values
    assert predict.prop_dispersion() == PROP_DISPERSION
    # an old bundle without fitted alphas keeps the config values
    joblib.dump({"models": {}}, skater)
    assert predict.prop_dispersion() == PROP_DISPERSION
    # fitted alphas replace them, including a fitted 0 (Poisson) for hits (a new file: the bundle cache is keyed
    # on mtime, which a rewrite within the same tick wouldn't change)
    skater = tmp_path / "skater_new.joblib"
    monkeypatch.setattr(predict, "SKATER_BUNDLE", skater)
    joblib.dump({"models": {}, "dispersion": {"hits": 0.0, "blocked_shots": 0.05, "goals": 0.0}}, skater)
    joblib.dump({"models": {}, "dispersion": {"saves": 0.01}}, goalie)
    alphas = predict.prop_dispersion()
    assert alphas == {"hits": 0.0, "blocked_shots": 0.05, "goals": 0.0, "saves": 0.01}
    assert math.isclose(prop_probability({"hits": 1.2}, "player_hits", 0.5, "Over"), 1 - math.exp(-1.2))
    assert prop_probability({"saves": 25.0}, "player_total_saves", 24.5, "Over") < 1 - poisson_cdf(24, 25.0)

def poisson_cdf(k, lam):
    from scipy.stats import poisson
    return float(poisson.cdf(k, lam))

def test_anytime_goal_yes_is_at_least_one_goal():
    assert math.isclose(prop_probability({"goals": 0.4}, "player_goal_scorer_anytime", 0.5, "Yes"), 1 - math.exp(-0.4))
