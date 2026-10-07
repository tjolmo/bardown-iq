import numpy as np
import pytest
from predictions import vig
from predictions.vig import devig, devig_two_way, implied_prob, shin_z, _shin_probs, _bisect

LONGSHOT = implied_prob([300, -500])          # 0.25, 0.8333: a juiced goals over/under


@pytest.mark.parametrize("method", vig.METHODS)
def test_sums_to_one_and_stays_in_unit_interval(method):
    rng = np.random.default_rng(1)
    fair = rng.dirichlet([2, 2], 500)
    q = fair * rng.uniform(1.0, 1.15, (500, 1))   # add a 0-15% overround
    p = devig(q, method)
    assert np.allclose(p.sum(1), 1)
    assert (p > 0).all() and (p < 1).all()
    three = devig(np.array([0.4, 0.35, 0.33]), method)
    assert np.isclose(three.sum(), 1) and three[0] > three[1] > three[2]


@pytest.mark.parametrize("method", vig.METHODS)
def test_symmetric_market_is_fifty_fifty_and_no_margin_is_unchanged(method):
    assert np.allclose(devig(implied_prob([-110, -110]), method), [0.5, 0.5])
    assert np.allclose(devig(np.array([0.3, 0.7]), method), [0.3, 0.7], atol=1e-9)


@pytest.mark.parametrize("method", vig.METHODS)
def test_monotonic_in_the_quoted_price(method):
    # shortening the over (more implied probability) at a fixed under price must raise fair P(over)
    overs = np.linspace(0.1, 0.9, 40)
    q = np.stack([overs, np.full_like(overs, 0.55)], 1)
    p = devig(q, method)[:, 0]
    assert (np.diff(p) > 0).all()


def test_known_values_multiplicative_and_additive():
    assert np.allclose(devig(LONGSHOT, "multiplicative"), [0.25 / (0.25 + 5 / 6), (5 / 6) / (0.25 + 5 / 6)])
    margin = 0.25 + 5 / 6 - 1
    assert np.allclose(devig(LONGSHOT, "additive"), [0.25 - margin / 2, 5 / 6 - margin / 2])


def test_power_solves_sum_q_to_the_k():
    p = devig(LONGSHOT, "power")
    k = np.log(p[0]) / np.log(LONGSHOT[0])
    assert k > 1
    assert np.isclose(np.log(p[1]) / np.log(LONGSHOT[1]), k)
    assert np.isclose((LONGSHOT ** k).sum(), 1)


def test_shin_closed_form_matches_root_finding_and_model_identity():
    q = np.array([[0.25, 5 / 6], [0.6, 0.45], [0.1, 0.95], [0.5238, 0.5238]])
    z_closed = shin_z(q)
    z_iter = _bisect(lambda z: _shin_probs(q, z).sum(-1) - 1, np.zeros(4), np.full(4, 0.999))
    assert np.allclose(z_closed, z_iter, atol=1e-8)
    # symmetric market: z equals the overround
    assert np.isclose(z_closed[3], q[3].sum() - 1)
    # Shin's model: q_i is proportional to sqrt(z p_i + (1 - z) p_i^2)
    p = devig(q, "shin")
    implied = np.sqrt(z_closed[:, None] * p + (1 - z_closed[:, None]) * p ** 2)
    assert np.allclose(implied / implied.sum(1, keepdims=True), q / q.sum(1, keepdims=True))


def test_longshot_bias_ordering():
    # multiplicative leaves the most probability on the long shot; the others move margin onto it
    p = {m: devig(LONGSHOT, m)[0] for m in vig.METHODS}
    assert all(p["multiplicative"] > p[m] for m in ("additive", "power", "shin"))


def test_devig_two_way_vectorised_and_unknown_method():
    p = devig_two_way([300, -110, 150], [-500, -110, -180], "shin")
    assert p.shape == (3,) and np.isclose(p[1], 0.5)
    with pytest.raises(ValueError):
        devig(LONGSHOT, "bogus")
