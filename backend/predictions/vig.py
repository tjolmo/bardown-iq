"""Removing the bookmaker margin (vig/overround) from quoted prices to get fair probabilities.

Every function takes implied probabilities q (1 / decimal odds, summing to more than 1) along the LAST axis and
returns fair probabilities summing to 1 along that axis. Inputs can be one market (shape (n,)) or many markets
stacked (shape (rows, n)); two-outcome over/under markets are the common case (`devig_two_way`).

Methods:
- multiplicative: q_i / sum(q). Spreads the margin in proportion to each price, so a heavy favourite and a long shot
  carry the same relative margin. Ignores the favourite-longshot bias.
- additive: q_i - (sum(q) - 1) / n. The same absolute margin on every side, so long shots carry relatively more
  (can go negative for extreme long shots; clipped).
- power: q_i ** k with k > 1 chosen so the result sums to 1. Shrinks small probabilities proportionally more.
- shin: Shin (1992/1993) insider-trading model. z is the share of money from insiders; the book prices so that
  q_i = sqrt(z p_i + (1 - z) p_i^2) up to normalisation, which loads the margin on long shots. Closed form for two
  outcomes, root-finding on z otherwise.
"""
import numpy as np

METHODS = ("multiplicative", "additive", "power", "shin")
_EPS = 1e-12


def american_to_decimal(american):
    a = np.asarray(american, float)
    return np.where(a > 0, 1 + a / 100, 1 + 100 / np.abs(a))


def implied_prob(american):
    """Raw (vig-inclusive) implied probability of American odds."""
    return 1 / american_to_decimal(american)


def _as2d(q):
    q = np.asarray(q, float)
    return np.atleast_2d(q), q.ndim == 1


def multiplicative(q):
    q2, one = _as2d(q)
    p = q2 / q2.sum(-1, keepdims=True)
    return p[0] if one else p


def additive(q):
    q2, one = _as2d(q)
    n = q2.shape[-1]
    p = q2 - (q2.sum(-1, keepdims=True) - 1) / n
    p = np.clip(p, _EPS, None)
    p = p / p.sum(-1, keepdims=True)   # only changes anything when a side was clipped
    return p[0] if one else p


def _bisect(f, lo, hi, iters=200):
    """Vectorised bisection for an increasing-or-decreasing f with a sign change on [lo, hi] (per row)."""
    lo, hi = np.array(lo, float), np.array(hi, float)
    f_lo = f(lo)
    for _ in range(iters):
        mid = (lo + hi) / 2
        f_mid = f(mid)
        same = np.sign(f_mid) == np.sign(f_lo)
        lo, f_lo = np.where(same, mid, lo), np.where(same, f_mid, f_lo)
        hi = np.where(same, hi, mid)
    return (lo + hi) / 2


def power(q):
    q2, one = _as2d(q)
    q2 = np.clip(q2, _EPS, 1 - _EPS)
    rows = q2.shape[0]
    # sum(q^k) - 1 is decreasing in k; k = 1 at zero margin; k < 1 handles an underround (sum < 1)
    k = _bisect(lambda k: (q2 ** k[:, None]).sum(-1) - 1, np.full(rows, 0.01), np.full(rows, 100.0))
    p = q2 ** k[:, None]
    p = p / p.sum(-1, keepdims=True)
    return p[0] if one else p


def _shin_probs(q, z):
    """Shin fair probabilities for insider share z (per row) given implied probabilities q."""
    b = q.sum(-1, keepdims=True)
    z = z[:, None]
    return (np.sqrt(z ** 2 + 4 * (1 - z) * q ** 2 / b) - z) / (2 * (1 - z))


def shin_z(q):
    """Shin's insider share z per market. Two outcomes: closed form; otherwise root-finding on sum(p) = 1."""
    q2, _ = _as2d(q)
    b = q2.sum(-1)
    if q2.shape[-1] == 2:
        # solving sum p_i = 1 for two outcomes reduces to a linear equation in u = 1 - z
        d = (q2[:, 0] ** 2 - q2[:, 1] ** 2) / b
        u = 2 * (1 - (q2 ** 2).sum(-1) / b) / (1 - d ** 2)
        z = 1 - u
    else:
        z = _bisect(lambda z: _shin_probs(q2, z).sum(-1) - 1, np.zeros(len(b)), np.full(len(b), 0.999))
    return np.where(b > 1, np.clip(z, 0, 0.999), 0.0)


def shin(q):
    q2, one = _as2d(q)
    z = shin_z(q2)
    p = _shin_probs(q2, z)
    # no margin (or an underround): Shin is undefined, fall back to normalising
    p = np.where((q2.sum(-1) > 1)[:, None], p, q2 / q2.sum(-1, keepdims=True))
    p = p / p.sum(-1, keepdims=True)   # removes floating-point drift only
    return p[0] if one else p


_FUNCS = {"multiplicative": multiplicative, "additive": additive, "power": power, "shin": shin}


def devig(q, method="multiplicative"):
    """Fair probabilities from implied probabilities q (last axis = outcomes of one market)."""
    try:
        return _FUNCS[method](q)
    except KeyError:
        raise ValueError(f"unknown vig method {method!r}; choose from {METHODS}") from None


def devig_two_way(over_american, under_american, method="multiplicative"):
    """Vig-free P(over) for arrays of two-sided American prices."""
    q = np.stack([implied_prob(over_american), implied_prob(under_american)], axis=-1)
    return devig(np.atleast_2d(q), method)[:, 0]
