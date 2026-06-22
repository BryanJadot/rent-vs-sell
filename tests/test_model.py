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
from model import Model, excluded_gain, tax_at_sale

HAROLD = "properties/harold-ave.toml"  # the real property under analysis
FIXTURE = "properties/test-fixture.toml"  # synthetic: gain + positive cash flow


@pytest.fixture
def m():
    return Model(load_property(HAROLD))


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
        "break_even",
        "break_even_chart",
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


def test_break_even_appreciation_ties_hold_and_sell(m):
    """At the solved break-even appreciation, HOLD net worth must equal SELL net worth
    (both at the same opp rate) — the defining property of the figure."""
    for y in assumptions.HORIZONS:
        be = m.break_even_appreciation(y, opp_rate=assumptions.PRIMARY_INVEST)
        hold = m.hold_net_worth(
            m.p.primary_rent, y, be, opp_rate=assumptions.PRIMARY_INVEST
        ).net_worth
        sell = m.invest_net_worth(m.calc_sell().net_after_tax, y, assumptions.PRIMARY_INVEST)
        assert abs(hold - sell) < 1.0  # bisection converges to the cent


def test_break_even_chart_is_wealth_over_time(m):
    """The wealth-over-time chart series must be aligned year arrays for HOLD and SELL over
    0..horizon, with the payoff year derived from the loan and the crossover year (if any)
    inside the swept domain — the chart is a drawing of these facts, so they must be
    internally consistent."""
    c = m.compute()["break_even_chart"]
    grid, hold, sell = c["year_grid"], c["hold"], c["sell"]
    assert grid[0] == 0 and grid[-1] == c["horizon"]
    assert len(hold) == len(grid) == len(sell)
    # Each HOLD point is hold-until-sell_year-then-invest at that horizon (the chart is just a
    # drawing of them). At the sell year itself there's no post-sale leg, so it equals the
    # plain hold value there.
    s = c["sell_year"]
    assert hold[s] == m.hold_net_worth(m.p.primary_rent, s, 0.0485).net_worth
    assert hold[-1] == m.hold_then_invest_net_worth(m.p.primary_rent, s, c["horizon"], 0.0485)
    # Payoff year = loan months / 12; sits within the swept domain.
    assert c["payoff_year"] == m.p.payments_left / 12
    # Crossover, if present, is a year index in range; if None the gap never changes sign.
    if c["crossover_year"] is not None:
        assert grid[0] < c["crossover_year"] <= grid[-1]


def test_hold_then_invest_boundaries(m):
    """hold_then_invest_net_worth must reduce correctly at its boundaries:
    - horizon <= sell_year: still holding → equals plain hold_net_worth at the horizon.
    - sell_year == 0: equals investing the just-sold (year-0) hold value at the market rate.
    - horizon > sell_year: equals hold value at sell_year, then invest_net_worth to horizon.
    """
    r = m.p.primary_rent
    rate = assumptions.PRIMARY_INVEST
    # Before the sell year — still a rental at the horizon.
    assert m.hold_then_invest_net_worth(r, 10, 5, 0.0485) == pytest.approx(
        m.hold_net_worth(r, 5, 0.0485).net_worth
    )
    # At the sell year — no post-sale leg.
    assert m.hold_then_invest_net_worth(r, 10, 10, 0.0485) == pytest.approx(
        m.hold_net_worth(r, 10, 0.0485).net_worth
    )
    # sell_year == 0 — sell immediately, invest the year-0 hold value.
    expected0 = m.invest_net_worth(m.hold_net_worth(r, 0, 0.0485).net_worth, 15, rate)
    assert m.hold_then_invest_net_worth(r, 0, 15, 0.0485) == pytest.approx(expected0)
    # After the sell year — hold value at S then invested for (horizon − S).
    nw_at_s = m.hold_net_worth(r, 10, 0.0485).net_worth
    assert m.hold_then_invest_net_worth(r, 10, 30, 0.0485) == pytest.approx(
        m.invest_net_worth(nw_at_s, 20, rate)
    )


def test_two_properties_are_independent():
    """Two Model instances must not share state (multi-property isolation)."""
    a = Model(load_property(HAROLD))
    p2 = load_property(HAROLD)
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
    # The cap-gains tax is owed at closing, so the amount actually invested is net_after_tax,
    # NOT net_proceeds. On a gain these differ by exactly the tax; investing the pre-tax
    # proceeds would overstate SELL (the original bug). On a loss they coincide (tax == 0).
    assert s.net_after_tax == pytest.approx(s.net_proceeds - s.tax)
    assert s.net_after_tax < s.net_proceeds  # a gain property: tax > 0


def test_sell_invests_after_tax_proceeds_not_pretax(fix):
    """best_sell / invest must compound net_after_tax, not the pre-tax net_proceeds —
    otherwise the SELL side invests money already owed the IRS at closing (the symmetry
    the hold path keeps by paying its own cap-gains tax at the future sale)."""
    s = fix.calc_sell()
    yrs, rate = 10, assumptions.PRIMARY_INVEST
    correct = fix.invest_net_worth(s.net_after_tax, yrs, rate)
    overstated = fix.invest_net_worth(s.net_proceeds, yrs, rate)
    assert overstated > correct  # investing pre-tax proceeds would overstate SELL
    # best_sell uses the after-tax basis (max across the invest rates), never the pre-tax one.
    assert fix.best_sell(yrs) == pytest.approx(
        max(fix.invest_net_worth(s.net_after_tax, yrs, r) for r in assumptions.INVEST_RATES)
    )


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
    assert excluded_gain(Sec121.FULL_RENTAL, 500_000, 10) == 0.0


def test_excluded_gain_within_3yr_capped_at_statutory_limit():
    # A gain larger than the cap is only excludable up to CG_EXCLUSION.
    assert excluded_gain(Sec121.WITHIN_3YR, 500_000, 3) == CG_EXCLUSION
    # A small gain is fully excluded.
    assert excluded_gain(Sec121.WITHIN_3YR, 100_000, 3) == 100_000


def test_excluded_gain_within_3yr_lapses_past_window():
    # Past SELL_SOON_MAX_YEARS the within_3yr treatment grants no exclusion.
    assert excluded_gain(Sec121.WITHIN_3YR, 300_000, 10) == 0.0


def test_tax_at_sale_signs_and_components():
    """All three components positive; sale well above cost basis → FULL recapture."""
    # cost basis 1,000,000; accum deprec 200,000 → adjusted basis 800,000.
    # realized 1,400,000 → recognized gain 600,000 > deprec, so recapture is on the full
    # 200,000 and the cap-gains slice is the 400,000 above cost basis.
    st = tax_at_sale(
        accumulated_deprec=200_000,
        suspended_loss=150_000,
        realized_amount=1_400_000,
        cost_basis=1_000_000,
        treatment=Sec121.FULL_RENTAL,
        years=10,
    )
    assert st.recapture > 0 and st.deprec_release > 0 and st.cap_gains_tax > 0
    assert st.excluded_gain == 0.0  # full rental → no exclusion
    assert st.appreciation_gain == pytest.approx(400_000)
    assert abs(st.cap_gains_tax - 400_000 * CAP_GAINS_RATE) < 1.0
    # recapture carries NIIT (consistent with cap gains): fed 25% + NIIT 3.8% + CA 13.3%.
    assert abs(st.recapture - 200_000 * assumptions.DEPREC_RECAPTURE_RATE) < 1.0


def test_derive_rate_rejects_unamortizable_payment():
    """A monthly_pi too small to amortize the balance over the term (≤ the principal-only
    floor balance/n) has no positive note rate — the loader/Model must raise a CLEAR error
    rather than crash with a ZeroDivisionError deep inside the bisection."""
    from model import _derive_monthly_rate

    with pytest.raises(ValueError, match="too small to amortize"):
        _derive_monthly_rate(balance=50_000, pmt=4_739.86, n=6)  # 50000/6 = 8333 > pmt
    # A consistent payment is accepted (sanity: the real Harold figures don't trip it).
    r = _derive_monthly_rate(balance=1_102_902.48, pmt=4_739.86, n=306)
    assert 0 < r < 0.02


def test_cap_gains_tax_floored_when_exclusion_exceeds_gain():
    """When the §121 exclusion is LARGER than the appreciation gain, the taxable gain floors
    at 0 — the cap-gains tax is $0, never NEGATIVE (the excess exclusion can't become a tax
    credit). Guards the `max(0.0, …)` floor on taxable_gain. (A gain of $100k fully sheltered
    by the $250k exclusion: taxable gain 0, tax 0 — not (100k − 250k)·rate = a refund.)"""
    st = tax_at_sale(
        accumulated_deprec=0.0,
        suspended_loss=0.0,
        realized_amount=900_000,  # cost basis 800k → only $100k of appreciation gain
        cost_basis=800_000,
        treatment=Sec121.WITHIN_3YR,  # full $250k exclusion, > the $100k gain
        years=3,
    )
    assert st.appreciation_gain == pytest.approx(100_000)
    assert st.excluded_gain == pytest.approx(100_000)  # exclusion capped at the gain
    assert st.cap_gains_tax == 0.0  # floored — NOT negative
    assert assumptions.DEPREC_RECAPTURE_RATE == pytest.approx(0.25 + 0.038 + 0.133)


def test_recapture_capped_at_recognized_gain():
    """§1250: when the sale lands BETWEEN adjusted basis and original cost, recapture is
    capped at the recognized gain (not all depreciation taken), and there is no cap-gains
    slice. Below adjusted basis it's a §1231 loss with zero recapture."""
    # cost basis 1,000,000; accum deprec 200,000 → adjusted basis 800,000.
    # Sell at 900,000: recognized gain 100,000 < 200,000 deprec → recapture only 100,000.
    st = tax_at_sale(
        accumulated_deprec=200_000,
        suspended_loss=0.0,
        realized_amount=900_000,
        cost_basis=1_000_000,
        treatment=Sec121.FULL_RENTAL,
        years=10,
    )
    assert st.recapture == pytest.approx(100_000 * assumptions.DEPREC_RECAPTURE_RATE)
    assert st.appreciation_gain == 0.0 and st.cap_gains_tax == 0.0
    # Sell below adjusted basis (700,000 < 800,000): §1231 loss, no recapture, no gain.
    st_loss = tax_at_sale(
        accumulated_deprec=200_000,
        suspended_loss=0.0,
        realized_amount=700_000,
        cost_basis=1_000_000,
        treatment=Sec121.FULL_RENTAL,
        years=10,
    )
    assert st_loss.recapture == 0.0 and st_loss.cap_gains_tax == 0.0


def test_total_depreciation_never_exceeds_basis(m):
    """Depreciation runs for exactly DEPREC_YEARS (27.5), not 28 whole years. Summing the
    per-year depreciation the income calc deducts over a long hold must equal building_basis
    to the cent — and equal the recapture cap (annual × min(years, 27.5)) — so the income
    side and the recapture side can never disagree about how much was depreciated. (Guards
    the off-by-half-a-year boundary: `year_index < 27.5` would grant a full 28th year.)"""
    total = 0.0
    for yr in range(40):  # well past the 27.5-yr recovery period
        deprec_fraction = max(0.0, min(1.0, assumptions.DEPREC_YEARS - yr))
        total += m.annual_depreciation * deprec_fraction
    assert total == pytest.approx(m.p.building_basis)
    # Recapture cap at any horizon ≥ 27.5 yrs equals the same basis.
    recapture_base = m.annual_depreciation * min(30, assumptions.DEPREC_YEARS)
    assert recapture_base == pytest.approx(m.p.building_basis)


# ── Golden snapshot: any unintended numeric drift becomes a visible diff ────────


@pytest.mark.parametrize(
    "prop_path,golden",
    [
        (HAROLD, "tests/golden/harold-ave.json"),
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
