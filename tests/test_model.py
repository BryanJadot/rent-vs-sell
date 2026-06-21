"""Tests for the financial math in model.py. These lock the invariants that would
silently corrupt the analysis if an assumption or formula were edited wrongly."""

import json
import os

import pytest

import assumptions
from assumptions import (
    load_property,
    Sec121,
    CG_EXCLUSION,
    APPRECIATION,
    MONTHS_PER_YEAR,
    CAP_GAINS_RATE,
)
from model import Model, DEFAULT_PROPERTY, excluded_gain, tax_at_sale

FIXTURE = "properties/test-fixture.toml"  # synthetic: gain + positive cash flow


@pytest.fixture
def m():
    return Model(load_property(DEFAULT_PROPERTY))


@pytest.fixture
def fix():
    """Synthetic property: home_value > basis (taxed gain) and positive cash flow."""
    return Model(load_property(FIXTURE))


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


def test_iterative_and_closed_form_balances_agree(m):
    """The looped amortization schedule and the closed-form balance must agree at
    every horizon — independent computations cross-checking the amortization math."""
    for y in (1, 3, 5, 10, 20):
        _, looped = m.principal_paid_over(y)
        closed = m.remaining_balance_closed_form(y)
        assert abs(looped - closed) < 0.01, f"mismatch at {y}yr: {looped} vs {closed}"


def test_sell_today_is_a_loss_with_zero_tax(m):
    s = m.calc_sell()
    assert s.capital_gain < 0  # value below basis
    assert s.tax == 0.0  # a loss is not taxed
    assert abs(s.net_proceeds - (s.price - s.total_costs - s.payoff)) < 1.0


def test_sale_costs_match_rate(m):
    s = m.calc_sell()
    assert abs(s.total_costs - m.p.home_value * assumptions.SALE_COST_RATE) < 1.0


def test_move_back_exclusion_never_exceeds_cap_or_gain(m):
    for y in assumptions.HORIZONS:
        hr = m.hold_net_worth(
            m.p.primary_rent, y, assumptions.PRIMARY_APPRECIATION, sec121=Sec121.MOVE_BACK
        )
        assert hr.excluded_gain <= CG_EXCLUSION + 1
        assert hr.excluded_gain <= hr.appreciation_gain + 1


def test_within_3yr_only_excludes_at_short_horizons(m):
    # At >SELL_SOON_MAX_YEARS the within_3yr treatment must NOT grant an exclusion.
    hr = m.hold_net_worth(
        m.p.primary_rent, 10, assumptions.PRIMARY_APPRECIATION, sec121=Sec121.WITHIN_3YR
    )
    assert hr.excluded_gain == 0.0


def test_higher_appreciation_yields_higher_net_worth(m):
    """Monotonicity: more appreciation => more hold net worth, all else equal."""
    nw = [
        m.hold_net_worth(m.p.primary_rent, 20, a).net_worth
        for a in (APPRECIATION["low"], APPRECIATION["moderate"], APPRECIATION["high"])
    ]
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
    for key in (
        "inputs",
        "sell",
        "hold_grid",
        "sell_grid",
        "rent_growth_sensitivity",
        "opp_rate_sensitivity",
        "worked_example",
        "risk",
        "cash_facts",
    ):
        assert key in d
    # cash_facts holds neutral cash figures only — NO beats/trails verdict or win count
    # (interpretation is produced downstream, not in compute()).
    cf = d["cash_facts"]
    assert cf["yr1_oop"] == pytest.approx(-m.oop_breakdown(m.p.primary_rent).net)
    for interp_key in ("win_cells", "verb_10", "central_edge", "upside", "downside"):
        assert interp_key not in cf


def test_suspended_losses_zero_when_usable_yearly(m, monkeypatch):
    monkeypatch.setattr("model.PASSIVE_LOSS_USABLE_YEARLY", True)
    assert m.suspended_operating_losses(m.p.primary_rent, 10) == 0.0


def test_suspended_losses_pool_is_drawn_down_by_profitable_years(m):
    """§469: the carryforward pool must NET later profitable years, not just sum losses.
    Over a long enough hold the rental turns tax-positive (rent grows, interest shrinks),
    so the released pool at 20yr must be <= the pool at the point it peaks. Concretely it
    should be strictly less than the naive sum-of-loss-years would give."""
    naive_sum = 0.0
    sched = m.amortization_schedule(20)
    for yr in range(20):
        r = m.calc_rent(m.p.primary_rent * (1 + m.rent_growth) ** yr, year_index=yr)
        ti = r.egi - r.op_expenses - sched[yr][0] - m.annual_depreciation
        if ti < 0:
            naive_sum += -ti
    netted = m.suspended_operating_losses(m.p.primary_rent, 20)
    assert netted < naive_sum  # profitable years drew the pool down
    assert netted >= 0.0


def test_hold_cash_flow_uses_same_investment_rule_as_sell(m):
    """Symmetry: a single dollar of (negative) cash flow carried to the horizon must be
    transformed identically to the SELL side's grow-pre-tax-tax-the-gain-once rule."""
    rate = assumptions.PRIMARY_INVEST
    years = 15
    # one unit of cash flow in year 0 -> compounded over (years-1) full years
    t = years - 1
    expected_factor = 1 + ((1 + rate) ** t - 1) * (1 - CAP_GAINS_RATE)
    # invest_net_worth on $1 over t years gives exactly that factor
    assert abs(m.invest_net_worth(1.0, t, rate) - expected_factor) < 1e-9


def test_rent_growth_sensitivity_higher_growth_helps_hold(m):
    """Higher rent growth must (weakly) raise hold net worth at every horizon, and the
    sensitivity block must report both rates with the high rate ABOVE the low."""
    rgs = m.compute()["rent_growth_sensitivity"]
    assert rgs["rg_high"] > rgs["rg_low"]
    for _, row in rgs["rows"].items():
        assert row["high"] >= row["low"]  # faster rent growth never hurts the hold case


def test_major_repair_modeled_net_of_tax(m):
    """A major repair is a capital improvement, so its modeled cost is below the gross
    cash outlay (basis-driven tax recovery)."""
    assert 0 < m.net_major_repair < assumptions.MAJOR_REPAIR


def test_two_properties_are_independent():
    """Two Model instances must not share state (multi-property isolation)."""
    a = Model(load_property(DEFAULT_PROPERTY))
    p2 = load_property(DEFAULT_PROPERTY)
    p2.home_value = 2_000_000
    b = Model(p2)
    assert b.calc_sell().price == 2_000_000
    assert a.calc_sell().price == a.p.home_value != b.calc_sell().price


# ── Taxed / positive-cash-flow paths (exercised only by the synthetic fixture) ──


def test_sell_with_gain_is_taxed(fix):
    """Fixture value > basis → the cap-gains sell-tax line must actually fire.
    (The real property is a loss, so this path is otherwise never executed.)"""
    s = fix.calc_sell()
    assert s.capital_gain > 0
    expected = max(0.0, s.capital_gain - CG_EXCLUSION) * CAP_GAINS_RATE
    assert abs(s.tax - expected) < 1.0


def test_positive_cash_flow_path(fix):
    """Fixture has high rent vs. a small loan → at least one rent level should
    produce positive year-1 cash flow (the real property never does)."""
    flows = [fix.calc_rent(r).cash_flow for r in fix.p.rent_levels]
    assert max(flows) > 0


def test_within_3yr_excludes_at_boundary_not_beyond(fix):
    """§121 'within_3yr' must grant the exclusion at exactly SELL_SOON_MAX_YEARS
    and NOT one year later."""
    at = fix.hold_net_worth(
        fix.p.primary_rent,
        assumptions.SELL_SOON_MAX_YEARS,
        assumptions.PRIMARY_APPRECIATION,
        sec121=Sec121.WITHIN_3YR,
    )
    beyond = fix.hold_net_worth(
        fix.p.primary_rent,
        assumptions.SELL_SOON_MAX_YEARS + 1,
        assumptions.PRIMARY_APPRECIATION,
        sec121=Sec121.WITHIN_3YR,
    )
    assert at.excluded_gain > 0
    assert beyond.excluded_gain == 0.0


def test_invest_net_worth_zero_and_negative_proceeds(m):
    assert m.invest_net_worth(0.0, 10, 0.07) == 0.0
    # negative proceeds (underwater): a "loss" compounds; tax on negative gain is 0-ish
    assert m.invest_net_worth(-100_000, 10, 0.07) < 0


def test_hold_at_zero_years_is_equity_minus_gains_tax(fix):
    """years=0 edge: no growth/cash flow/recapture, but the EXISTING gain is still
    taxed (fixture value > basis). net worth = value − loan − sale costs − gains tax."""
    hr = fix.hold_net_worth(fix.p.primary_rent, 0, assumptions.PRIMARY_APPRECIATION)
    expected = (
        fix.p.home_value
        - fix.p.mortgage_bal
        - fix.p.home_value * assumptions.SALE_COST_RATE
        - hr.cap_gains_tax
    )
    assert hr.cash_flow_fv == 0.0 and hr.recapture == 0.0
    assert abs(hr.net_worth - expected) < 1.0


# ── Pure tax functions (extracted from hold_net_worth) ──────────────────────────


def test_excluded_gain_full_rental_is_zero():
    assert excluded_gain(Sec121.FULL_RENTAL, 500_000, 10, 4.5) == 0.0


def test_excluded_gain_within_3yr_capped_at_statutory_limit():
    # A gain larger than the cap is only excludable up to CG_EXCLUSION.
    assert excluded_gain(Sec121.WITHIN_3YR, 500_000, 3, 4.5) == CG_EXCLUSION
    # A small gain is fully excluded.
    assert excluded_gain(Sec121.WITHIN_3YR, 100_000, 3, 4.5) == 100_000


def test_excluded_gain_move_back_prorates_by_qualified_use():
    # residence (4.5 + 2) / total (4.5 + 10 + 2) of a $300k gain, capped at CG_EXCLUSION.
    g = excluded_gain(Sec121.MOVE_BACK, 300_000, 10, 4.5)
    frac = (4.5 + 2) / (4.5 + 10 + 2)
    assert abs(g - min(CG_EXCLUSION, 300_000 * frac)) < 1.0


def test_tax_at_sale_signs_and_components():
    """All three components are returned as positive dollar amounts."""
    st = tax_at_sale(
        accumulated_deprec=200_000,
        suspended_loss=150_000,
        appreciation_gain=400_000,
        treatment=Sec121.FULL_RENTAL,
        years=10,
        years_owned_as_residence=4.5,
    )
    assert st.recapture > 0 and st.deprec_release > 0 and st.cap_gains_tax > 0
    assert st.excluded_gain == 0.0  # full rental → no exclusion
    # cap gains is taxed on the whole gain (no exclusion) at the cap-gains rate
    assert abs(st.cap_gains_tax - 400_000 * CAP_GAINS_RATE) < 1.0


# ── Golden snapshot: any unintended numeric drift becomes a visible diff ────────


@pytest.mark.parametrize(
    "prop_path,golden",
    [
        (DEFAULT_PROPERTY, "tests/golden/harold-ave.json"),
        (FIXTURE, "tests/golden/test-fixture.json"),
    ],
)
def test_matches_golden_snapshot(prop_path, golden):
    """compute() output must match the committed golden file (regenerate
    deliberately with `make snapshot` after verifying an intended change)."""
    assert os.path.exists(golden), f"missing golden file {golden} — run make snapshot"
    expected = json.load(open(golden))
    actual = json.loads(json.dumps(Model(load_property(prop_path)).compute(), sort_keys=True))
    _assert_close(actual, expected, path="")


def _assert_close(a, b, path, tol=0.01):
    """Recursive near-equality for the nested compute() dict (floats within tol)."""
    assert type(a) is type(b), f"type mismatch at {path}: {type(a)} vs {type(b)}"
    if isinstance(a, dict):
        assert a.keys() == b.keys(), f"key mismatch at {path}: {a.keys() ^ b.keys()}"
        for k in a:
            _assert_close(a[k], b[k], f"{path}.{k}", tol)
    elif isinstance(a, list):
        assert len(a) == len(b), f"length mismatch at {path}"
        for i, (x, y) in enumerate(zip(a, b)):
            _assert_close(x, y, f"{path}[{i}]", tol)
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        assert abs(a - b) <= tol, f"value drift at {path}: {a} vs {b}"
    else:
        assert a == b, f"mismatch at {path}: {a!r} vs {b!r}"
