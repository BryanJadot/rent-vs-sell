"""Tests for the financial math in model.py. These lock the invariants that would
silently corrupt the analysis if an assumption or formula were edited wrongly."""

import pytest

import assumptions
from assumptions import load_property, CG_EXCLUSION, APPRECIATION, MONTHS_PER_YEAR, CAP_GAINS_RATE
from model import Model, DEFAULT_PROPERTY


@pytest.fixture
def m():
    return Model(load_property(DEFAULT_PROPERTY))


def test_derived_rate_reproduces_payment(m):
    """The bisection-solved monthly rate must reproduce the actual P&I payment."""
    r = m.monthly_rate
    n = m.p.payments_left
    bal = m.p.mortgage_bal
    implied_pmt = bal * r / (1 - (1 + r) ** -n)
    assert abs(implied_pmt - m.p.monthly_pi) < 0.01


def test_amortization_pays_off_by_term(m):
    """After all remaining payments, the loan balance should reach ~0."""
    _, remaining = m.principal_paid_over(m.p.payments_left // MONTHS_PER_YEAR + 1)
    assert abs(remaining) < 1.0


def test_principal_paid_is_positive_and_bounded(m):
    paid, remaining = m.principal_paid_over(10)
    assert paid > 0
    assert remaining < m.p.mortgage_bal
    assert abs((paid + remaining) - m.p.mortgage_bal) < 1.0


def test_sell_today_is_a_loss_with_zero_tax(m):
    s = m.calc_sell()
    assert s.capital_gain < 0          # value below basis
    assert s.tax == 0.0                # a loss is not taxed
    assert abs(s.net_proceeds - (s.price - s.total_costs - s.payoff)) < 1.0


def test_sale_costs_match_rate(m):
    s = m.calc_sell()
    assert abs(s.total_costs - m.p.home_value * assumptions.SALE_COST_RATE) < 1.0


def test_move_back_exclusion_never_exceeds_cap_or_gain(m):
    for y in assumptions.HORIZONS:
        hr = m.hold_net_worth(m.p.primary_rent, y, assumptions.PRIMARY_APPRECIATION,
                              sec121="move_back")
        assert hr.excluded_gain <= CG_EXCLUSION + 1
        assert hr.excluded_gain <= hr.appreciation_gain + 1


def test_within_3yr_only_excludes_at_short_horizons(m):
    # At >SELL_SOON_MAX_YEARS the within_3yr treatment must NOT grant an exclusion.
    hr = m.hold_net_worth(m.p.primary_rent, 10, assumptions.PRIMARY_APPRECIATION,
                          sec121="within_3yr")
    assert hr.excluded_gain == 0.0


def test_higher_appreciation_yields_higher_net_worth(m):
    """Monotonicity: more appreciation => more hold net worth, all else equal."""
    nw = [m.hold_net_worth(m.p.primary_rent, 20, a).net_worth
          for a in (APPRECIATION["low"], APPRECIATION["moderate"], APPRECIATION["high"])]
    assert nw[0] < nw[1] < nw[2]


def test_sell_invest_is_after_tax(m):
    """invest_net_worth must tax the gain (be below the pre-tax compounding)."""
    np_ = m.calc_sell().net_proceeds
    pre_tax = np_ * (1 + 0.07) ** 20
    after_tax = m.invest_net_worth(np_, 20, 0.07)
    assert after_tax < pre_tax
    gain = pre_tax - np_
    assert abs((pre_tax - after_tax) - gain * CAP_GAINS_RATE) < 1.0


def test_compute_dict_is_complete(m):
    d = m.compute()
    for key in ("inputs", "sell", "hold_grid", "sell_grid", "worked_example",
                "risk", "verdict"):
        assert key in d
    v = d["verdict"]
    assert v["total_cells"] == len(m.p.realistic_rents) * len(assumptions.HORIZONS)
    assert 0 <= v["win_cells"] <= v["total_cells"]


def test_suspended_losses_zero_when_usable_yearly(m, monkeypatch):
    monkeypatch.setattr("model.PASSIVE_LOSS_USABLE_YEARLY", True)
    assert m.suspended_operating_losses(m.p.primary_rent, 10) == 0.0


def test_two_properties_are_independent():
    """Two Model instances must not share state (multi-property isolation)."""
    a = Model(load_property(DEFAULT_PROPERTY))
    p2 = load_property(DEFAULT_PROPERTY)
    p2.home_value = 2_000_000
    b = Model(p2)
    assert b.calc_sell().price == 2_000_000
    assert a.calc_sell().price == a.p.home_value != b.calc_sell().price
