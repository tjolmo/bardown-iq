import numpy as np
from predictions.dispersion import fit_alpha, nb2_loglik, poisson_loglik
from predictions.train import _dispersion

rng = np.random.default_rng(7)

def _nb_sample(mu, alpha):
    # gamma-Poisson mixture: mean mu, variance mu(1 + alpha mu)
    return rng.poisson(rng.gamma(1 / alpha, alpha * mu))

def test_nb2_loglik_matches_scipy_and_tends_to_poisson():
    from scipy.stats import nbinom
    y, mu = np.array([0, 1, 3, 7]), np.array([0.4, 1.2, 2.5, 4.0])
    n = 1 / 0.2
    assert np.allclose(nb2_loglik(y, mu, 0.2), nbinom.logpmf(y, n, n / (n + mu)))
    assert np.allclose(nb2_loglik(y, mu, 1e-7), poisson_loglik(y, mu), atol=1e-5)
    assert np.allclose(nb2_loglik(y, mu, 0.0), poisson_loglik(y, mu))

def test_recovers_alpha_of_over_dispersed_counts():
    mu = rng.uniform(0.3, 3.0, 60_000)
    fit = fit_alpha(_nb_sample(mu, 0.15), mu)
    assert abs(fit["alpha_mle"] - 0.15) < 0.02
    assert abs(fit["alpha_mom"] - 0.15) < 0.03
    assert fit["alpha"] == fit["alpha_mle"] and fit["loglik_gain"] > 0.0005

def test_poisson_and_under_dispersed_counts_stay_poisson():
    mu = rng.uniform(0.3, 3.0, 60_000)
    assert fit_alpha(rng.poisson(mu), mu)["alpha"] == 0.0
    # binomial counts are narrower than Poisson: the likelihood peaks at alpha 0
    p = rng.uniform(0.05, 0.3, 60_000)
    under = fit_alpha(rng.binomial(10, p), 10 * p)
    assert under["alpha"] == 0.0 and under["alpha_mle"] == 0.0 and under["alpha_mom"] == 0.0

def test_small_gain_below_threshold_prices_as_poisson():
    mu = rng.uniform(0.3, 3.0, 60_000)
    fit = fit_alpha(_nb_sample(mu, 0.15), mu, min_gain=1.0)
    assert fit["alpha"] == 0.0 and fit["alpha_mle"] > 0.1

def test_alpha_is_clamped():
    mu = rng.uniform(0.3, 3.0, 20_000)
    assert fit_alpha(_nb_sample(mu, 3.0), mu, max_alpha=1.0)["alpha_mle"] <= 1.0

def test_bundle_dispersion_collects_each_targets_alpha():
    metrics = {"train_rows": 10, "valid_rows": 5, "hits": {"dispersion": {"alpha": 0.1}},
               "goals": {"dispersion": {"alpha": 0.0}}, "assists": {"trees": 3}}
    assert _dispersion(metrics) == {"hits": 0.1, "goals": 0.0}
