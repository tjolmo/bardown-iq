"""Negative-binomial (NB2) dispersion for pricing count props: variance = mu(1 + alpha mu), alpha 0 = Poisson.

The count models are Poisson regressions, so their mean is right but a Poisson around it can be too narrow: hits and
blocks vary game to game more than their rate explains (scorer, score effects, role). Training estimates alpha per
target from the validation split (a model fit on earlier dates predicting the held-out recent games), so the alpha
that prices props is measured out of sample and refreshes with every retrain. The NB is used only where it beats the
Poisson on that validation log likelihood by DISPERSION_MIN_GAIN; under-dispersed stats clamp to alpha 0 (Poisson).
"""
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import gammaln

from .config import DISPERSION_MAX_ALPHA, DISPERSION_MIN_GAIN

_MU_FLOOR = 1e-6


def poisson_loglik(y, mu) -> np.ndarray:
    y, mu = np.asarray(y, float), np.clip(np.asarray(mu, float), _MU_FLOOR, None)
    return y * np.log(mu) - mu - gammaln(y + 1)


def nb2_loglik(y, mu, alpha) -> np.ndarray:
    """Per-row NB2 log likelihood with mean mu and variance mu(1 + alpha mu); alpha 0 falls back to the Poisson."""
    if alpha <= 0:
        return poisson_loglik(y, mu)
    y, mu = np.asarray(y, float), np.clip(np.asarray(mu, float), _MU_FLOOR, None)
    n = 1 / alpha
    return (gammaln(y + n) - gammaln(n) - gammaln(y + 1)
            + n * np.log(n / (n + mu)) + y * np.log(mu / (n + mu)))


def alpha_moments(y, mu) -> float:
    """Method-of-moments alpha: excess squared residual over the Poisson variance, per unit of mu^2 (clamped >= 0)."""
    y, mu = np.asarray(y, float), np.asarray(mu, float)
    return max(0.0, float(np.sum((y - mu) ** 2 - mu) / np.sum(mu ** 2)))


def fit_alpha(y, mu, max_alpha: float = DISPERSION_MAX_ALPHA, min_gain: float = DISPERSION_MIN_GAIN) -> dict:
    """Maximum-likelihood NB2 alpha for observed counts y around predicted means mu, in [0, max_alpha].
    Returns the MLE (`alpha_mle`), the moments cross-check (`alpha_mom`), the mean per-row log-likelihood gain of
    the NB over the Poisson (`loglik_gain`), and `alpha`: the MLE where that gain reaches `min_gain`, else 0."""
    ok = np.isfinite(np.asarray(y, float)) & np.isfinite(np.asarray(mu, float))
    y, mu = np.asarray(y, float)[ok], np.asarray(mu, float)[ok]
    base = float(poisson_loglik(y, mu).mean())
    res = minimize_scalar(lambda a: -nb2_loglik(y, mu, a).mean(), bounds=(1e-6, max_alpha), method="bounded",
                          options={"xatol": 1e-5})
    a = float(res.x)
    gain = float(-res.fun) - base
    if gain <= 0:       # under-dispersed (or exactly Poisson): the likelihood peaks at the boundary
        a, gain = 0.0, 0.0
    return {"alpha": round(a, 4) if gain >= min_gain else 0.0, "alpha_mle": round(a, 4),
            "alpha_mom": round(alpha_moments(y, mu), 4), "loglik_gain": round(gain, 5), "rows": int(len(y))}
