#!/usr/bin/env python3
"""
model.py — PURE MATH for the rent-vs-sell analysis.

No presentation here. A Model wraps one Property (per-house inputs from a TOML) plus
the shared assumptions in assumptions.py, derives the mortgage rate / depreciation /
risk drag once, and exposes the calculations + a compute() that bundles every result
into a plain dict (the contract consumed by render.py).

The comparison is apples-to-apples:
  • HOLD subtracts selling costs AND capital-gains tax at the FUTURE sale.
  • HOLD's negative cash flow + idle reserve are charged the AFTER-TAX opportunity
    cost (the SELL path is taxed on its gains, so symmetry requires after-tax).
  • SELL proceeds are compounded and the investment gain is taxed at liquidation.

render.py calls compute() in-process; running model.py standalone instead dumps the
dict to output/model_output.json as a standalone AUDIT ARTIFACT (so every computed
number can be inspected/diffed — e.g. by a CPA). It is not an input to render.

Run:  python3 model.py [properties/<file>.toml]   ->  writes output/model_output.json
"""

from dataclasses import dataclass, asdict
import json

from assumptions import (
    Property,
    load_property,
    Sec121,
    PROPERTY_TAX_GROWTH,
    EXPENSE_GROWTH,
    VACANCY_RATE,
    MGMT_RATE,
    TENANCY_YEARS,
    LEASING_FEE_MONTHS,
    RENT_GROWTH,
    BUILDING_PCT,
    DEPREC_YEARS,
    MARGINAL_TAX,
    DEPREC_RECAPTURE_RATE,
    CAP_GAINS_RATE,
    CG_EXCLUSION,
    MOVE_BACK_YEARS,
    SELL_SOON_MAX_YEARS,
    PASSIVE_LOSS_USABLE_YEARLY,
    BAD_VACANCY_MONTHS,
    EVICTION_COST,
    MAJOR_REPAIR,
    RISK_VACANCY_PROB,
    RISK_EVICTION_PROB,
    RISK_REPAIR_PROB,
    BROKER_RATE,
    TRANSFER_TAX,
    TITLE_ESCROW,
    SALE_COST_RATE,
    INVEST_RATES,
    PRIMARY_INVEST,
    AFTERTAX_OPP,
    APPRECIATION,
    PRIMARY_APPRECIATION,
    HORIZONS,
    WORKED_EXAMPLE_HORIZON,
    MONTHS_PER_YEAR,
)

DEFAULT_PROPERTY = "properties/harold-ave.toml"


@dataclass
class Sell:
    price: float
    broker: float
    transfer: float
    title: float
    total_costs: float
    payoff: float
    net_proceeds: float
    capital_gain: float
    tax: float


@dataclass
class Rent:
    monthly_rent: float
    gross: float
    vacancy: float
    egi: float
    mgmt: float
    leasing: float
    fixed_costs: float
    op_expenses: float
    noi: float
    annual_pi: float
    cash_flow: float
    principal_paydown: float


@dataclass
class OopBreakdown:
    """Year-1 real cash in/out of the bank account (named so callers don't index a
    tuple positionally). Outflows are NEGATIVE; `net` is the sum (a drain when < 0)."""

    rent_in: float  # rent collected, net of vacancy (+)
    mortgage_out: float  # full P&I payment (−)
    opex_out: float  # tax + insurance + repairs + mgmt + leasing (−)
    tax_back: float  # yearly depreciation shield, 0 when passive losses suspended (+)
    net: float  # rent_in + mortgage_out + opex_out + tax_back


@dataclass
class HoldResult:
    future_value: float
    remaining_loan: float
    sale_costs: float
    gross_equity: float
    cash_flow_fv: float
    deprec_release: float
    recapture: float
    appreciation_gain: float
    excluded_gain: float
    cap_gains_tax: float
    reserve_opp_cost: float
    net_worth: float


def _derive_monthly_rate(balance: float, pmt: float, n: int) -> float:
    """Bisection solve for the monthly rate that reproduces the payment.

    We know the balance, the payment, and the number of payments left, but not the
    note rate. The standard amortization identity pmt = bal·r / (1 − (1+r)^−n) can't
    be solved for r in closed form, so we bisect on r in [0, 2%/mo] until the implied
    payment matches. 200 iterations converges far past cent precision.
    """
    lo, hi = 0.0, 0.02
    for _ in range(200):
        r = (lo + hi) / 2
        calc = balance * r / (1 - (1 + r) ** -n) if r > 0 else balance / n
        if calc > pmt:
            hi = r
        else:
            lo = r
    return r


def excluded_gain(
    treatment: Sec121, appreciation_gain: float, years: int, years_owned_as_residence: float
) -> float:
    """How much of the future capital gain the §121 exclusion shelters, in dollars.

    Rule (IRC §121): up to CG_EXCLUSION of gain on a primary residence is tax-free if
    you owned AND used it as your main home ≥2 of the last 5 years before sale. A pure
    rental fails the use test entirely. The three treatments model the realistic options:

      FULL_RENTAL  → rented continuously, never re-occupied: fails the use test, $0 excluded.
      WITHIN_3YR   → sold soon enough that the 2-of-5 test is still met (only valid up to
                     SELL_SOON_MAX_YEARS of renting): full exclusion, capped at CG_EXCLUSION.
      MOVE_BACK    → move back in for MOVE_BACK_YEARS before selling to re-qualify. Post-2008
                     law (the Housing Assistance Act) prorates the exclusion by the
                     "qualified use" fraction = residence-years / total-ownership-years, so
                     renting it out dilutes how much you can exclude. APPROXIMATE — the real
                     non-qualified-use rules have more nuance; confirm with a CPA.

    Returns a non-negative dollar amount, never exceeding the gain or the statutory cap.
    """
    if treatment == Sec121.WITHIN_3YR and years <= SELL_SOON_MAX_YEARS:
        return min(CG_EXCLUSION, appreciation_gain)
    if treatment == Sec121.MOVE_BACK:
        residence_yrs = years_owned_as_residence + MOVE_BACK_YEARS
        total_yrs = years_owned_as_residence + years + MOVE_BACK_YEARS
        qualified_fraction = min(1.0, residence_yrs / total_yrs)
        return min(CG_EXCLUSION, appreciation_gain * qualified_fraction)
    return 0.0  # FULL_RENTAL, or WITHIN_3YR past the eligibility window


@dataclass
class SaleTax:
    """The three taxes triggered when a held rental is finally sold."""

    recapture: float  # depreciation recapture (a cost, positive number)
    deprec_release: float  # suspended passive losses freed at sale (a benefit, positive)
    cap_gains_tax: float  # tax on appreciation above basis, net of §121 (a cost, positive)
    excluded_gain: float  # §121 exclusion applied (for display/audit)


def tax_at_sale(
    accumulated_deprec: float,
    suspended_loss: float,
    appreciation_gain: float,
    treatment: Sec121,
    years: int,
    years_owned_as_residence: float,
) -> SaleTax:
    """All taxes that land at the future sale of a property held as a rental.

    Three independent pieces, kept separate so each can be reasoned about and tested:

      • RECAPTURE: depreciation taken while renting is "recaptured" at sale —
        accumulated_deprec × DEPREC_RECAPTURE_RATE (fed unrecaptured §1250 25% + CA
        taxes it as ordinary income). A cost. Returned positive; the caller subtracts it.

      • DEPREC_RELEASE: for a high-MAGI owner, yearly rental losses are *suspended*
        (no annual deduction) and released all at once at sale, deductible at the
        ordinary MARGINAL_TAX rate → a benefit. suspended_loss is the accumulated loss.
        (If PASSIVE_LOSS_USABLE_YEARLY, suspended_loss is 0 because it was used yearly.)
        NOTE: recapture and release nearly cancel for a CA high earner because CA taxes
        recapture at roughly the same rate the loss is deducted at — by design, not a bug.

      • CAP_GAINS_TAX: the appreciation above original cost basis, minus any §121
        exclusion, taxed at CAP_GAINS_RATE (fed LT 20% + NIIT 3.8% + CA 13.3%). A cost.

    All amounts are positive dollars; signs are applied by the caller. Rates are flat
    effective rates — a simplification; real brackets are graduated.
    """
    recapture = accumulated_deprec * DEPREC_RECAPTURE_RATE
    deprec_release = suspended_loss * MARGINAL_TAX
    excluded = excluded_gain(treatment, appreciation_gain, years, years_owned_as_residence)
    taxable_gain = max(0.0, appreciation_gain - excluded)
    cap_gains_tax = taxable_gain * CAP_GAINS_RATE
    return SaleTax(recapture, deprec_release, cap_gains_tax, excluded)


class Model:
    """One property's rent-vs-sell analysis. Per-property inputs come from `prop`;
    shared market/tax assumptions are module-level imports. Derived per-property
    values (mortgage rate, depreciation, expected risk drag) are computed once here."""

    def __init__(self, prop: Property):
        self.p = prop
        # Derived mortgage figures
        self.monthly_rate = _derive_monthly_rate(
            prop.mortgage_bal, prop.monthly_pi, prop.payments_left
        )
        self.apr = self.monthly_rate * MONTHS_PER_YEAR
        # Derived depreciation
        self.annual_depreciation = (prop.cost_basis * BUILDING_PCT) / DEPREC_YEARS
        self.annual_deprec_shield = (
            self.annual_depreciation * MARGINAL_TAX if PASSIVE_LOSS_USABLE_YEARLY else 0.0
        )
        # Expected annual risk drag (vacancy term counts only EXCESS beyond baseline)
        self.excess_vacancy_months = BAD_VACANCY_MONTHS - MONTHS_PER_YEAR * VACANCY_RATE
        self.expected_risk_drag = (
            RISK_VACANCY_PROB * (self.excess_vacancy_months * prop.primary_rent)
            + RISK_EVICTION_PROB * EVICTION_COST
            + RISK_REPAIR_PROB * MAJOR_REPAIR
        )

    # ── Mortgage ──────────────────────────────────────────────────────────────
    def amortization_schedule(self, years: int) -> list[tuple[float, float]]:
        """Year-by-year (interest_paid, ending_balance) for the first `years` years.

        The single source of truth for amortization — both principal_paid_over and
        suspended_operating_losses consume it, so the per-month interest math (and the
        bal<=0 payoff guard) live in exactly one place. Caps at payments_left so a
        horizon past the loan term doesn't keep "paying" a zero balance.
        """
        bal = self.p.mortgage_bal
        months_left = self.p.payments_left
        out = []
        for _ in range(years):
            interest_yr = 0.0
            for _ in range(MONTHS_PER_YEAR):
                if months_left <= 0 or bal <= 0:
                    break
                interest = bal * self.monthly_rate
                interest_yr += interest
                bal -= self.p.monthly_pi - interest
                months_left -= 1
            out.append((interest_yr, bal))
        return out

    def principal_paid_over(self, years: int) -> tuple[float, float]:
        """Returns (principal paid, remaining balance) after `years` of payments."""
        sched = self.amortization_schedule(years)
        remaining = sched[-1][1] if sched else self.p.mortgage_bal
        return self.p.mortgage_bal - remaining, remaining

    def remaining_balance_closed_form(self, years: int) -> float:
        """Remaining balance via the closed-form amortization identity (no loop):
            B_k = B_0·(1+r)^k − pmt·((1+r)^k − 1)/r
        Independent of the iterative schedule above — `test_amortization` cross-checks
        the two agree, which guards against an off-by-one or sign error in the loop."""
        r = self.monthly_rate
        k = min(years * MONTHS_PER_YEAR, self.p.payments_left)
        if r == 0:
            return self.p.mortgage_bal - self.p.monthly_pi * k
        growth = (1 + r) ** k
        return self.p.mortgage_bal * growth - self.p.monthly_pi * (growth - 1) / r

    # ── Sell today ────────────────────────────────────────────────────────────
    def calc_sell(self) -> Sell:
        p = self.p
        broker = p.home_value * BROKER_RATE
        transfer = p.home_value * TRANSFER_TAX
        title = p.home_value * TITLE_ESCROW
        total = broker + transfer + title
        net = p.home_value - total - p.mortgage_bal
        gain = p.home_value - p.cost_basis  # negative => a loss
        tax = 0.0 if gain <= CG_EXCLUSION else (gain - CG_EXCLUSION) * CAP_GAINS_RATE
        return Sell(p.home_value, broker, transfer, title, total, p.mortgage_bal, net, gain, tax)

    # ── Rent (year-1 economics; year_index inflates fixed costs) ───────────────
    def calc_rent(self, monthly_rent: float, year_index: int = 0) -> Rent:
        p = self.p
        gross = monthly_rent * MONTHS_PER_YEAR
        vacancy = gross * VACANCY_RATE
        egi = gross - vacancy
        mgmt = egi * MGMT_RATE
        leasing = (monthly_rent * LEASING_FEE_MONTHS) / TENANCY_YEARS
        prop_tax = p.property_tax * (1 + PROPERTY_TAX_GROWTH) ** year_index
        other_fixed = (p.insurance + p.repairs) * (1 + EXPENSE_GROWTH) ** year_index
        fixed = prop_tax + other_fixed
        op = fixed + mgmt + leasing
        noi = egi - op
        annual_pi = p.monthly_pi * MONTHS_PER_YEAR
        cash_flow = noi - annual_pi
        yr1_principal, _ = self.principal_paid_over(1)
        return Rent(
            monthly_rent,
            gross,
            vacancy,
            egi,
            mgmt,
            leasing,
            fixed,
            op,
            noi,
            annual_pi,
            cash_flow,
            yr1_principal,
        )

    def oop_breakdown(self, monthly_rent: float) -> OopBreakdown:
        """Year-1 real cash flows (what hits the bank account). Outflows negative."""
        r = self.calc_rent(monthly_rent)
        rent_in = r.egi
        mortgage_out = -r.annual_pi
        opex_out = -(r.fixed_costs + r.mgmt + r.leasing)
        tax_back = self.annual_deprec_shield
        net = rent_in + mortgage_out + opex_out + tax_back
        return OopBreakdown(rent_in, mortgage_out, opex_out, tax_back, net)

    # ── Multi-year hold ────────────────────────────────────────────────────────
    def compounded_cash_flow(self, monthly_rent: float, years: int, opp_rate: float) -> float:
        """FV at horizon of each year's cash flow (rent grows, expenses inflate,
        risk drag subtracted), carried forward at the after-tax `opp_rate`."""
        fv = 0.0
        for yr in range(years):
            rent_this_yr = monthly_rent * (1 + RENT_GROWTH) ** yr
            cf = (
                self.calc_rent(rent_this_yr, year_index=yr).cash_flow
                + self.annual_deprec_shield
                - self.expected_risk_drag
            )
            fv += cf * (1 + opp_rate) ** (years - yr - 1)
        return fv

    def suspended_operating_losses(self, monthly_rent: float, years: int) -> float:
        """Sum of yearly rental TAX losses (rent − op-ex − mortgage INTEREST −
        depreciation), suspended under high MAGI and released at sale. Positive
        number; $0 if passive losses are usable yearly.

        Only mortgage INTEREST is deductible (not principal), so we take the per-year
        interest from the shared amortization schedule rather than the full payment.
        """
        if PASSIVE_LOSS_USABLE_YEARLY:
            return 0.0
        total_loss = 0.0
        schedule = self.amortization_schedule(years)
        for yr in range(years):
            interest_yr = schedule[yr][0]
            rent_this_yr = monthly_rent * (1 + RENT_GROWTH) ** yr
            r = self.calc_rent(rent_this_yr, year_index=yr)
            taxable_income = r.egi - r.op_expenses - interest_yr - self.annual_depreciation
            if taxable_income < 0:
                total_loss += -taxable_income
        return total_loss

    def hold_net_worth(
        self,
        monthly_rent: float,
        years: int,
        appr: float,
        opp_rate: float = PRIMARY_INVEST,
        sec121: Sec121 = Sec121.FULL_RENTAL,
    ) -> HoldResult:
        """Net worth from RENTING the property out, holding `years`, then selling.

        This is the "hold" side of the rent-vs-sell comparison, fully loaded so it's
        apples-to-apples with the "sell now and invest" side. Built from these pieces:

          gross_equity   = grown home value − remaining loan − selling costs at sale
          + cash_fv      = future value of all the (mostly negative) rental cash flows
          + deprec_release − recapture − cap_gains_tax   (the three taxes at sale)
          − reserve_opp_cost   = return forgone by parking the landlord reserve in cash
          = net_worth

        `sec121` selects the future-sale §121 treatment (see the Sec121 enum).
        `opp_rate` is the PRE-tax investment rate; the hold side is charged its
        AFTER-tax version (see below) so both sides are compared net of tax.
        """
        p = self.p

        # Equity at the future sale: home grown at `appr`, less the loan still owed,
        # less the cost to sell (same SALE_COST_RATE we'd pay selling today — counted
        # here too so the hold side isn't unfairly spared the eventual transaction cost).
        future_value = p.home_value * (1 + appr) ** years
        _, remaining = self.principal_paid_over(years)
        sale_costs = future_value * SALE_COST_RATE
        gross_equity = future_value - remaining - sale_costs

        # Cash flow is money you feed the property; it can't also be invested, so it's
        # charged the AFTER-TAX opportunity cost. We use after-tax (not the raw 7%)
        # because the SELL side IS taxed on its investment gains — charging the hold
        # side a pre-tax rate would unfairly penalize it. Symmetric treatment.
        aftertax_rate = opp_rate * (1 - CAP_GAINS_RATE)
        cash_fv = self.compounded_cash_flow(monthly_rent, years, aftertax_rate)

        # Taxes triggered at the sale (recapture, released suspended losses, cap gains).
        # Depreciation stops accruing after the 27.5-yr schedule ends, hence the min().
        accumulated_deprec = self.annual_depreciation * min(years, DEPREC_YEARS)
        suspended_loss = self.suspended_operating_losses(monthly_rent, years)
        appreciation_gain = max(0.0, future_value - p.cost_basis)
        st = tax_at_sale(
            accumulated_deprec,
            suspended_loss,
            appreciation_gain,
            sec121,
            years,
            p.years_owned_as_residence,
        )

        # The reserve sits in cash the whole hold instead of compounding — count the
        # forgone (after-tax) growth as a real cost of choosing to hold.
        reserve_opp_cost = p.cash_reserve * ((1 + aftertax_rate) ** years - 1)

        net_worth = (
            gross_equity
            + cash_fv
            + st.deprec_release
            - st.recapture
            - st.cap_gains_tax
            - reserve_opp_cost
        )
        return HoldResult(
            future_value,
            remaining,
            sale_costs,
            gross_equity,
            cash_fv,
            st.deprec_release,
            st.recapture,
            appreciation_gain,
            st.excluded_gain,
            st.cap_gains_tax,
            reserve_opp_cost,
            net_worth,
        )

    def invest_net_worth(self, net_proceeds: float, years: int, rate: float) -> float:
        """SELL path: proceeds compounded, investment gain taxed at LT cap-gains at
        liquidation — symmetric with the hold path's taxed home gain."""
        ending = net_proceeds * (1 + rate) ** years
        gain = ending - net_proceeds
        return ending - gain * CAP_GAINS_RATE

    def best_sell(self, years: int) -> float:
        np_ = self.calc_sell().net_proceeds
        return max(self.invest_net_worth(np_, years, r) for r in INVEST_RATES)

    # ── Compute: bundle everything into a plain dict ───────────────────────────
    def compute(self) -> dict:
        p = self.p
        sell = self.calc_sell()
        np_ = sell.net_proceeds
        H = HORIZONS

        rent_rows = {}
        for r in p.rent_levels:
            rr = self.calc_rent(r)
            oop = self.oop_breakdown(r)
            rent_rows[r] = {
                "rent_obj": asdict(rr),
                "oop": {
                    "rent_in": oop.rent_in,
                    "mortgage_out": oop.mortgage_out,
                    "opex_out": oop.opex_out,
                    "tax_back": oop.tax_back,
                    "net_year": oop.net,
                    "net_month": oop.net / MONTHS_PER_YEAR,
                },
            }

        hold_grid = {}
        for sec in Sec121:
            hold_grid[sec.value] = {}
            for label, appr in APPRECIATION.items():
                hold_grid[sec.value][label] = {
                    rent: [asdict(self.hold_net_worth(rent, y, appr, sec121=sec)) for y in H]
                    for rent in p.rent_levels
                }

        sell_grid = {
            f"{int(r * 100)}%": [self.invest_net_worth(np_, y, r) for y in H] for r in INVEST_RATES
        }
        best_sell_by_h = {y: self.best_sell(y) for y in H}

        we = self.hold_net_worth(p.primary_rent, WORKED_EXAMPLE_HORIZON, PRIMARY_APPRECIATION)

        h10 = self.hold_net_worth(p.primary_rent, 10, PRIMARY_APPRECIATION).net_worth
        h20 = self.hold_net_worth(p.primary_rent, 20, PRIMARY_APPRECIATION).net_worth
        hz = max(H)
        hold_central_long = self.hold_net_worth(p.primary_rent, hz, PRIMARY_APPRECIATION).net_worth
        hold_low_long = self.hold_net_worth(p.primary_rent, hz, APPRECIATION["low"]).net_worth
        hold_high_long = self.hold_net_worth(p.primary_rent, hz, APPRECIATION["high"]).net_worth
        sell_long = self.best_sell(hz)

        win_cells = sum(
            1
            for r in p.realistic_rents
            for y in H
            if self.hold_net_worth(r, y, PRIMARY_APPRECIATION).net_worth > self.best_sell(y)
        )
        total_cells = len(p.realistic_rents) * len(H)

        weh = WORKED_EXAMPLE_HORIZON
        cum_oop_10 = sum(
            -(
                self.calc_rent(p.primary_rent * (1 + RENT_GROWTH) ** yr, year_index=yr).cash_flow
                + self.annual_deprec_shield
                - self.expected_risk_drag
            )
            for yr in range(weh)
        )
        yr1_oop = -self.oop_breakdown(p.primary_rent).net
        yr10_oop = -(
            self.calc_rent(
                p.primary_rent * (1 + RENT_GROWTH) ** (weh - 1), year_index=weh - 1
            ).cash_flow
            + self.annual_deprec_shield
            - self.expected_risk_drag
        )

        base = self.oop_breakdown(p.primary_rent).net
        worst_extra = BAD_VACANCY_MONTHS * p.primary_rent + EVICTION_COST + MAJOR_REPAIR
        risk = {
            "baseline": base,
            "extra_vacancy": -BAD_VACANCY_MONTHS * p.primary_rent,
            "eviction": -EVICTION_COST,
            "major_repair": -MAJOR_REPAIR,
            "worst_extra": -worst_extra,
            "worst_total": base - worst_extra,
        }

        return {
            "generated": p.as_of_date,
            "address": p.address,
            "inputs": {
                "home_value": p.home_value,
                "cost_basis": p.cost_basis,
                "mortgage_bal": p.mortgage_bal,
                "monthly_pi": p.monthly_pi,
                "apr": self.apr,
                "property_tax": p.property_tax,
                "insurance": p.insurance,
                "repairs": p.repairs,
                "vacancy_rate": VACANCY_RATE,
                "mgmt_rate": MGMT_RATE,
                "rent_growth": RENT_GROWTH,
                "property_tax_growth": PROPERTY_TAX_GROWTH,
                "expense_growth": EXPENSE_GROWTH,
                "marginal_tax": MARGINAL_TAX,
                "cap_gains_rate": CAP_GAINS_RATE,
                "deprec_recapture_rate": DEPREC_RECAPTURE_RATE,
                "sale_cost_rate": SALE_COST_RATE,
                "cg_exclusion": CG_EXCLUSION,
                "invest_rates": INVEST_RATES,
                "primary_invest": PRIMARY_INVEST,
                "aftertax_opp": AFTERTAX_OPP,
                "cash_reserve": p.cash_reserve,
                "annual_depreciation": self.annual_depreciation,
                "expected_risk_drag": self.expected_risk_drag,
                "excess_vacancy_months": self.excess_vacancy_months,
                "bad_vacancy_months": BAD_VACANCY_MONTHS,
                "eviction_cost": EVICTION_COST,
                "major_repair": MAJOR_REPAIR,
                "years_owned_residence": p.years_owned_as_residence,
                "appreciation": APPRECIATION,
                "primary_appreciation": PRIMARY_APPRECIATION,
                "horizons": H,
                "rent_levels": p.rent_levels,
                "realistic_rents": p.realistic_rents,
                "primary_rent": p.primary_rent,
            },
            "sell": asdict(sell),
            "rent_rows": rent_rows,
            "hold_grid": hold_grid,
            "sell_grid": sell_grid,
            "best_sell_by_horizon": best_sell_by_h,
            "worked_example": asdict(we),
            "risk": risk,
            "verdict": {
                "h10": h10,
                "h20": h20,
                "best_sell_10": self.best_sell(10),
                "best_sell_20": self.best_sell(20),
                "verb_10": _compare(h10, self.best_sell(10)),
                "verb_20": _compare(h20, self.best_sell(20)),
                "hold_low_long": hold_low_long,
                "hold_central_long": hold_central_long,
                "hold_high_long": hold_high_long,
                "sell_long": sell_long,
                "verb_low_long": _compare(hold_low_long, sell_long),
                "upside": hold_high_long - sell_long,
                "central_edge": hold_central_long - sell_long,
                "downside": hold_low_long - sell_long,
                "win_cells": win_cells,
                "total_cells": total_cells,
                "longest_horizon": hz,
                "cum_oop_10": cum_oop_10,
                "yr1_oop": yr1_oop,
                "yr10_oop": yr10_oop,
                "mo_oop": yr1_oop / MONTHS_PER_YEAR,
                "reserve_cost_yr": p.cash_reserve * AFTERTAX_OPP,
            },
        }


def _compare(hold_v: float, sell_v: float) -> str:
    diff = hold_v - sell_v
    # Tie band is 3% of the comparison magnitude. Use abs(sell_v) so a negative or
    # zero sell value can't invert the threshold (would otherwise never register a tie).
    if abs(diff) < 0.03 * abs(sell_v):
        return "roughly ties"
    return "beats" if diff > 0 else "trails"


def _main():
    import os
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PROPERTY
    model = Model(load_property(path))
    os.makedirs("output", exist_ok=True)
    with open("output/model_output.json", "w") as f:
        json.dump(model.compute(), f, indent=2)
    print(f"[output/model_output.json written for {path}]")


if __name__ == "__main__":
    _main()
