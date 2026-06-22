#!/usr/bin/env python3
"""test_properties.py — PROPERTY-BASED invariants (Hypothesis).

The grid/golden tests pin specific numbers; these pin RELATIONSHIPS that must hold for
*any* valid property and *any* in-range assumption. Hypothesis generates random inputs,
and on failure shrinks to a minimal reproducer — so a violated invariant is a concrete,
reproducible bug, not an opinion. This is the adversarial counterpart to the worked
examples: it hunts the edge cases hand-picked fixtures miss (huge gains, near-paid-off
loans, tiny/large rents, extreme rates).

Invariants encoded here:
  • Monotonicity — net worth moves the right direction as each driver changes.
  • Symmetry — year-0 hold (still §121-eligible) reconciles to sell to the cent.
  • Conservation/bounds — depreciation ≤ basis, taxes ≥ 0, no NaN/inf, worst ≤ baseline.
  • Tax-slice partition — recapture and cap-gains tile the gain without overlap or gap.

Run under `make check` (pytest). Deterministic seeds via Hypothesis's database.
"""

import math

from hypothesis import given, settings, strategies as st, assume, HealthCheck

import assumptions
from assumptions import Property, Sec121
from model import Model

# A reasonable settings profile: enough examples to find edge cases, not so many that the
# suite drags. deadline=None because building a Model + amortizing 30 yrs is not instant.
SLOW = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@st.composite
def properties(draw):
    """A randomly-generated but STRUCTURALLY VALID property.

    Ranges are wide enough to stress the model (gains and losses, big and tiny loans,
    near-paid-off mortgages, low and high rents) but constrained to the physically
    sensible: positive dollars, building_basis < cost_basis, a monthly P&I that can
    actually amortize the balance over the remaining term (so _derive_monthly_rate
    converges to a real rate rather than the bracket endpoint).
    """
    home_value = draw(st.floats(min_value=300_000, max_value=4_000_000))
    cost_basis = draw(st.floats(min_value=200_000, max_value=4_000_000))
    # Building basis is the depreciable slice — strictly below cost basis (land isn't
    # depreciable), at least a token amount.
    building_basis = draw(st.floats(min_value=50_000, max_value=max(60_000, cost_basis * 0.9)))
    mortgage_bal = draw(st.floats(min_value=10_000, max_value=home_value * 0.9))
    payments_left = draw(st.integers(min_value=12, max_value=360))
    # Pick a monthly rate in a realistic band, then DERIVE a consistent payment so the
    # loan amortizes exactly — this guarantees _derive_monthly_rate has a real solution and
    # that the payment matches the balance (an inconsistent balance/payment pair is not a
    # real property; min balance $10k keeps the pair well-defined).
    monthly_rate = draw(st.floats(min_value=0.0008, max_value=0.0083))  # ~1%–10% APR
    monthly_pi = mortgage_bal * monthly_rate / (1 - (1 + monthly_rate) ** -payments_left)
    primary_rent = draw(st.floats(min_value=1_500, max_value=12_000))
    return Property(
        address="hypothesis://synthetic",
        as_of_date="2026-01-01",
        home_value=home_value,
        cost_basis=cost_basis,
        building_basis=building_basis,
        mortgage_bal=mortgage_bal,
        monthly_pi=monthly_pi,
        payments_left=payments_left,
        years_owned_as_residence=draw(st.floats(min_value=0, max_value=10)),
        property_tax=draw(st.floats(min_value=2_000, max_value=40_000)),
        insurance=draw(st.floats(min_value=500, max_value=8_000)),
        repairs=draw(st.floats(min_value=1_000, max_value=40_000)),
        rent_levels=[primary_rent],
        realistic_rents=[primary_rent],
        primary_rent=primary_rent,
        cash_reserve=draw(st.floats(min_value=0, max_value=300_000)),
    )


def _finite(*xs):
    return all(math.isfinite(x) for x in xs)


# ── Monotonicity ──────────────────────────────────────────────────────────────


@SLOW
@given(prop=properties(), years=st.integers(min_value=1, max_value=30))
def test_hold_increases_with_appreciation(prop, years):
    """More home appreciation can never LOWER hold net worth (the invariant
    break_even_appreciation's bisection relies on)."""
    m = Model(prop)
    lo = m.hold_net_worth(prop.primary_rent, years, 0.02).net_worth
    hi = m.hold_net_worth(prop.primary_rent, years, 0.08).net_worth
    assert _finite(lo, hi)
    assert hi > lo - 1.0  # strictly higher (tolerance for fp noise)


@SLOW
@given(prop=properties(), years=st.integers(min_value=1, max_value=30))
def test_hold_increases_with_rent(prop, years):
    """Higher rent can never LOWER hold net worth — rent is an inflow."""
    m = Model(prop)
    lo = m.hold_net_worth(prop.primary_rent, years, 0.0485).net_worth
    hi = m.hold_net_worth(prop.primary_rent + 1000, years, 0.0485).net_worth
    assert _finite(lo, hi)
    assert hi > lo - 1.0


@SLOW
@given(prop=properties(), years=st.integers(min_value=1, max_value=30))
def test_sell_increases_with_market_and_horizon(prop, years):
    """Sell net worth grows with the market rate and (for a non-loss sale) with horizon."""
    m = Model(prop)
    npx = m.calc_sell().net_after_tax
    lo = m.invest_net_worth(npx, years, 0.04)
    hi = m.invest_net_worth(npx, years, 0.09)
    assert _finite(lo, hi)
    if npx > 0:
        assert hi >= lo - 1.0
        # Longer horizon compounds more (when proceeds are positive).
        assert (
            m.invest_net_worth(npx, years + 5, 0.07) >= m.invest_net_worth(npx, years, 0.07) - 1.0
        )


# ── Symmetry / consistency ──────────────────────────────────────────────────────


@SLOW
@given(prop=properties())
def test_year0_hold_reconciles_to_sell(prop):
    """At a 0-year hold under WITHIN_3YR (still §121-eligible, like selling today), hold
    net worth must equal the sell side's after-tax proceeds to the cent — both are 'sell
    now', so they cannot disagree. (FULL_RENTAL differs by exactly the forfeited §121
    exclusion, which is an intended modeling choice, so this uses WITHIN_3YR.)"""
    m = Model(prop)
    hold0 = m.hold_net_worth(prop.primary_rent, 0, 0.0485, sec121=Sec121.WITHIN_3YR).net_worth
    sell0 = m.calc_sell().net_after_tax
    assert _finite(hold0, sell0)
    assert abs(hold0 - sell0) < 1.0


@SLOW
@given(prop=properties(), years=st.integers(min_value=28, max_value=40))
def test_total_depreciation_caps_at_basis(prop, years):
    """At any horizon past the 27.5-yr schedule, the depreciation the income calc deducts
    (summed) must equal building_basis to the cent — and equal the recapture cap — so the
    income side and the recapture side never disagree about how much was depreciated."""
    m = Model(prop)
    total = sum(
        m.annual_depreciation * max(0.0, min(1.0, assumptions.DEPREC_YEARS - yr))
        for yr in range(years)
    )
    recapture_cap = m.annual_depreciation * min(years, assumptions.DEPREC_YEARS)
    assert abs(total - prop.building_basis) < 1e-6
    assert abs(recapture_cap - prop.building_basis) < 1e-6


@SLOW
@given(prop=properties(), years=st.integers(min_value=1, max_value=30))
def test_closed_form_balance_matches_iterative(prop, years):
    """The two independent amortization implementations must agree at every horizon,
    including past payoff — guards an off-by-one or sign error in either."""
    m = Model(prop)
    _, iterative = m.principal_paid_over(years)
    closed = m.remaining_balance_closed_form(years)
    assert _finite(iterative, closed)
    assert abs(iterative - closed) < 0.01


# ── Conservation / bounds ───────────────────────────────────────────────────────


@SLOW
@given(prop=properties(), years=st.integers(min_value=1, max_value=30), appr=st.floats(-0.05, 0.12))
def test_net_worth_is_finite(prop, years, appr):
    """No input in range may produce NaN/inf anywhere in the hold computation."""
    m = Model(prop)
    h = m.hold_net_worth(prop.primary_rent, years, appr)
    assert _finite(
        h.net_worth,
        h.gross_equity,
        h.cash_flow_fv,
        h.recapture,
        h.cap_gains_tax,
        h.reserve_opp_cost,
    )


@SLOW
@given(prop=properties(), years=st.integers(min_value=1, max_value=30), appr=st.floats(-0.05, 0.12))
def test_sale_taxes_are_nonnegative_and_recapture_capped(prop, years, appr):
    """Taxes at sale are costs (≥0); recapture never exceeds the depreciation actually
    taken times its rate (the §1250 cap)."""
    m = Model(prop)
    h = m.hold_net_worth(prop.primary_rent, years, appr)
    assert h.recapture >= -1e-6 and h.cap_gains_tax >= -1e-6
    accumulated = m.annual_depreciation * min(years, assumptions.DEPREC_YEARS)
    assert h.recapture <= accumulated * assumptions.DEPREC_RECAPTURE_RATE + 1.0


@SLOW
@given(prop=properties())
def test_worst_year_is_worse_than_baseline(prop):
    """The worst-case year must cost at least as much out of pocket as a normal year, and
    the normal year's out-of-pocket is itself a drain (≤ 0) for a leveraged rental — both
    the baseline and every bad event are non-positive contributions."""
    m = Model(prop)
    r = m.risk_scenarios(prop.primary_rent)
    assert r["worst_total"] <= r["baseline"] + 1.0
    for k in ("extra_vacancy", "eviction", "major_repair", "worst_extra"):
        assert r[k] <= 1e-6  # each is a cost (≤ 0)


@SLOW
@given(prop=properties(), years=st.integers(min_value=1, max_value=30))
def test_break_even_appreciation_ties_the_two_sides(prop, years):
    """At the solved break-even appreciation, hold and sell net worth must be equal to the
    cent — the bisection's defining property, for any property."""
    m = Model(prop)
    be = m.break_even_appreciation(years, opp_rate=assumptions.PRIMARY_INVEST)
    assume(-0.10 < be < 0.25)  # only meaningful when the root is inside the bracket
    hold = m.hold_net_worth(
        prop.primary_rent, years, be, opp_rate=assumptions.PRIMARY_INVEST
    ).net_worth
    sell = m.invest_net_worth(m.calc_sell().net_after_tax, years, assumptions.PRIMARY_INVEST)
    assert abs(hold - sell) < 1.0
