#!/usr/bin/env python3
"""test_metamorphic.py — METAMORPHIC invariants.

A different bug-detection mechanism from monotonicity/conservation: these transform the
INPUTS in a way whose effect on the OUTPUT is known EXACTLY, then check the model produced
that exact effect. They catch errors a single-run check can't — a wrong coefficient, a
dropped term, or a tax applied to the wrong base often survives "is it monotonic?" but
breaks "did doubling every dollar double the answer?".

Relations encoded:
  • Scale invariance — multiply every DOLLAR input (and every dollar CONSTANT) by k, leave
    rates alone → every dollar output scales by exactly k. The single strongest structural
    check: any term that isn't linear-homogeneous in dollars (a stray squared term, a
    constant that should have scaled, a hard-coded threshold) breaks it.
  • Zero-tax world — set every tax rate to 0 → recapture / cap-gains / their drag vanish,
    and sell net worth is just proceeds compounded with NO gain haircut.
  • §121 ordering — the exclusion can only help: WITHIN_3YR hold ≥ FULL_RENTAL hold.
  • Zero-rate sell — investing at 0% returns exactly the principal (no growth, no tax).
"""

import contextlib
import dataclasses

from hypothesis import given, settings, strategies as st, HealthCheck

import model as model_mod
from model import Model
from tests.test_properties import properties  # reuse the synthetic-property strategy


@contextlib.contextmanager
def _patched(**overrides):
    """Temporarily override module-level constants in model's namespace, restoring them on
    exit. A per-example context manager (not the function-scoped monkeypatch fixture, which
    Hypothesis does not reset between generated inputs)."""
    saved = {name: getattr(model_mod, name) for name in overrides}
    try:
        for name, val in overrides.items():
            setattr(model_mod, name, val)
        yield
    finally:
        for name, val in saved.items():
            setattr(model_mod, name, val)


SLOW = settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow])

# Dollar-denominated module constants that must scale alongside the property's dollar fields
# for scale-invariance to hold (rates are scale-free and stay put).
DOLLAR_CONSTANTS = ("EVICTION_COST", "MAJOR_REPAIR", "CG_EXCLUSION")
TAX_RATE_CONSTANTS = (
    "MARGINAL_TAX",
    "NIIT_RATE",
    "DEPREC_RECAPTURE_RATE",
    "CAP_GAINS_RATE",
)


def _scale_property(p, k):
    """A copy of property `p` with every DOLLAR field multiplied by k (rates/counts/dates
    unchanged). monthly_pi scales with the balance so the loan stays self-consistent."""
    return dataclasses.replace(
        p,
        home_value=p.home_value * k,
        cost_basis=p.cost_basis * k,
        building_basis=p.building_basis * k,
        mortgage_bal=p.mortgage_bal * k,
        monthly_pi=p.monthly_pi * k,
        property_tax=p.property_tax * k,
        insurance=p.insurance * k,
        repairs=p.repairs * k,
        rent_levels=[r * k for r in p.rent_levels],
        realistic_rents=[r * k for r in p.realistic_rents],
        primary_rent=p.primary_rent * k,
        cash_reserve=p.cash_reserve * k,
    )


@SLOW
@given(
    prop=properties(),
    years=st.integers(min_value=1, max_value=30),
    appr=st.floats(min_value=-0.02, max_value=0.10),
    k=st.floats(min_value=0.25, max_value=4.0),
)
def test_scale_invariance(prop, years, appr, k):
    """Multiplying every dollar input AND every dollar constant by k scales hold and sell
    net worth by exactly k. The model's money math must be linear-homogeneous in dollars;
    any non-scaling term (a hard threshold left un-scaled, a squared dollar, a constant that
    should have scaled) breaks this."""
    base_hold = Model(prop).hold_net_worth(prop.primary_rent, years, appr).net_worth
    base_sell = Model(prop).invest_net_worth(Model(prop).calc_sell().net_after_tax, years, 0.07)

    # Scale the dollar CONSTANTS in the model's namespace too, so thresholds move with the
    # money (CG_EXCLUSION especially — a fixed $250k would not scale and break the relation).
    overrides = {name: getattr(model_mod, name) * k for name in DOLLAR_CONSTANTS}
    with _patched(**overrides):
        sp = _scale_property(prop, k)
        scaled_hold = Model(sp).hold_net_worth(sp.primary_rent, years, appr).net_worth
        scaled_sell = Model(sp).invest_net_worth(Model(sp).calc_sell().net_after_tax, years, 0.07)

    # Relative tolerance (dollar figures can be millions; fp error scales with magnitude).
    assert abs(scaled_hold - base_hold * k) < max(1.0, abs(base_hold) * k * 1e-7)
    assert abs(scaled_sell - base_sell * k) < max(1.0, abs(base_sell) * k * 1e-7)


@SLOW
@given(prop=properties(), years=st.integers(min_value=1, max_value=30), appr=st.floats(0.0, 0.10))
def test_zero_tax_world(prop, years, appr):
    """With every tax rate set to 0: the sale-tax drags vanish (recapture and cap-gains tax
    are 0), and sell net worth is the proceeds compounded with NO gain haircut."""
    with _patched(**{name: 0.0 for name in TAX_RATE_CONSTANTS}):
        m = Model(prop)
        h = m.hold_net_worth(prop.primary_rent, years, appr)
        assert abs(h.recapture) < 1e-6
        assert abs(h.cap_gains_tax) < 1e-6
        # Sell with no tax = pure compounding of the (now untaxed) proceeds.
        npx = m.calc_sell().net_after_tax
        assert abs(m.invest_net_worth(npx, years, 0.07) - npx * (1.07**years)) < 1e-3


@SLOW
@given(prop=properties(), years=st.integers(min_value=1, max_value=30), appr=st.floats(-0.02, 0.10))
def test_section121_only_helps(prop, years, appr):
    """The §121 exclusion can only reduce tax, so the WITHIN_3YR hold can never be worth
    LESS than the FULL_RENTAL hold at the same inputs (they're equal once the gain is fully
    sheltered or past the eligibility window)."""
    from assumptions import Sec121

    m = Model(prop)
    w3 = m.hold_net_worth(prop.primary_rent, years, appr, sec121=Sec121.WITHIN_3YR).net_worth
    fr = m.hold_net_worth(prop.primary_rent, years, appr, sec121=Sec121.FULL_RENTAL).net_worth
    assert w3 >= fr - 1.0


@SLOW
@given(prop=properties(), years=st.integers(min_value=1, max_value=30))
def test_zero_rate_sell_returns_principal(prop, years):
    """Investing the proceeds at 0% returns exactly the principal — no growth, hence no
    gain and no tax. A nonzero result would mean a phantom return or a sign error."""
    m = Model(prop)
    npx = m.calc_sell().net_after_tax
    assert abs(m.invest_net_worth(npx, years, 0.0) - npx) < 1e-6
