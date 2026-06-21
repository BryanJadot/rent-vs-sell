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
    Property, load_property,
    PROPERTY_TAX_GROWTH, EXPENSE_GROWTH, VACANCY_RATE, MGMT_RATE, TENANCY_YEARS,
    LEASING_FEE_MONTHS, RENT_GROWTH, BUILDING_PCT, DEPREC_YEARS, MARGINAL_TAX,
    DEPREC_RECAPTURE_RATE, CAP_GAINS_RATE, CG_EXCLUSION, MOVE_BACK_YEARS,
    SELL_SOON_MAX_YEARS, PASSIVE_LOSS_USABLE_YEARLY, BAD_VACANCY_MONTHS, EVICTION_COST,
    MAJOR_REPAIR, RISK_VACANCY_PROB, RISK_EVICTION_PROB, RISK_REPAIR_PROB,
    BROKER_RATE, TRANSFER_TAX, TITLE_ESCROW, SALE_COST_RATE, INVEST_RATES,
    PRIMARY_INVEST, AFTERTAX_OPP, APPRECIATION, PRIMARY_APPRECIATION, HORIZONS,
    WORKED_EXAMPLE_HORIZON, MONTHS_PER_YEAR,
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
    """Bisection solve for the monthly rate that reproduces the payment."""
    lo, hi = 0.0, 0.02
    for _ in range(200):
        r = (lo + hi) / 2
        calc = balance * r / (1 - (1 + r) ** -n) if r > 0 else balance / n
        if calc > pmt:
            hi = r
        else:
            lo = r
    return r


class Model:
    """One property's rent-vs-sell analysis. Per-property inputs come from `prop`;
    shared market/tax assumptions are module-level imports. Derived per-property
    values (mortgage rate, depreciation, expected risk drag) are computed once here."""

    def __init__(self, prop: Property):
        self.p = prop
        # Derived mortgage figures
        self.monthly_rate = _derive_monthly_rate(prop.mortgage_bal, prop.monthly_pi,
                                                 prop.payments_left)
        self.apr = self.monthly_rate * MONTHS_PER_YEAR
        # Derived depreciation
        self.annual_depreciation = (prop.cost_basis * BUILDING_PCT) / DEPREC_YEARS
        self.annual_deprec_shield = (self.annual_depreciation * MARGINAL_TAX
                                     if PASSIVE_LOSS_USABLE_YEARLY else 0.0)
        # Expected annual risk drag (vacancy term counts only EXCESS beyond baseline)
        self.excess_vacancy_months = BAD_VACANCY_MONTHS - MONTHS_PER_YEAR * VACANCY_RATE
        self.expected_risk_drag = (
            RISK_VACANCY_PROB * (self.excess_vacancy_months * prop.primary_rent)
            + RISK_EVICTION_PROB * EVICTION_COST
            + RISK_REPAIR_PROB * MAJOR_REPAIR
        )

    # ── Mortgage ──────────────────────────────────────────────────────────────
    def principal_paid_over(self, years: int) -> tuple[float, float]:
        """Returns (principal paid, remaining balance) after `years` of payments."""
        bal = self.p.mortgage_bal
        months = min(years * MONTHS_PER_YEAR, self.p.payments_left)
        start = bal
        for _ in range(months):
            interest = bal * self.monthly_rate
            bal -= (self.p.monthly_pi - interest)
        return start - bal, bal

    # ── Sell today ────────────────────────────────────────────────────────────
    def calc_sell(self) -> Sell:
        p = self.p
        broker = p.home_value * BROKER_RATE
        transfer = p.home_value * TRANSFER_TAX
        title = p.home_value * TITLE_ESCROW
        total = broker + transfer + title
        net = p.home_value - total - p.mortgage_bal
        gain = p.home_value - p.cost_basis          # negative => a loss
        tax = 0.0 if gain <= CG_EXCLUSION else (gain - CG_EXCLUSION) * CAP_GAINS_RATE
        return Sell(p.home_value, broker, transfer, title, total,
                    p.mortgage_bal, net, gain, tax)

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
        return Rent(monthly_rent, gross, vacancy, egi, mgmt, leasing, fixed, op,
                    noi, annual_pi, cash_flow, yr1_principal)

    def oop_breakdown(self, monthly_rent: float):
        """Year-1 real cash flows (what hits the bank account):
        (rent_in, mortgage_out, opex_out, tax_back, net)."""
        r = self.calc_rent(monthly_rent)
        rent_in = r.egi
        mortgage_out = -r.annual_pi
        opex_out = -(r.fixed_costs + r.mgmt + r.leasing)
        tax_back = self.annual_deprec_shield
        net = rent_in + mortgage_out + opex_out + tax_back
        return rent_in, mortgage_out, opex_out, tax_back, net

    # ── Multi-year hold ────────────────────────────────────────────────────────
    def compounded_cash_flow(self, monthly_rent: float, years: int, opp_rate: float) -> float:
        """FV at horizon of each year's cash flow (rent grows, expenses inflate,
        risk drag subtracted), carried forward at the after-tax `opp_rate`."""
        fv = 0.0
        for yr in range(years):
            rent_this_yr = monthly_rent * (1 + RENT_GROWTH) ** yr
            cf = (self.calc_rent(rent_this_yr, year_index=yr).cash_flow
                  + self.annual_deprec_shield - self.expected_risk_drag)
            fv += cf * (1 + opp_rate) ** (years - yr - 1)
        return fv

    def suspended_operating_losses(self, monthly_rent: float, years: int) -> float:
        """Sum of yearly rental TAX losses (rent − op-ex − mortgage INTEREST −
        depreciation), suspended under high MAGI and released at sale. Positive
        number; $0 if passive losses are usable yearly."""
        if PASSIVE_LOSS_USABLE_YEARLY:
            return 0.0
        total_loss = 0.0
        bal = self.p.mortgage_bal
        for yr in range(years):
            interest_yr = 0.0
            for _ in range(MONTHS_PER_YEAR):
                if bal <= 0:
                    break
                i = bal * self.monthly_rate
                interest_yr += i
                bal -= (self.p.monthly_pi - i)
            rent_this_yr = monthly_rent * (1 + RENT_GROWTH) ** yr
            r = self.calc_rent(rent_this_yr, year_index=yr)
            taxable_income = r.egi - r.op_expenses - interest_yr - self.annual_depreciation
            if taxable_income < 0:
                total_loss += -taxable_income
        return total_loss

    def hold_net_worth(self, monthly_rent: float, years: int, appr: float,
                       opp_rate: float = PRIMARY_INVEST,
                       sec121: str = "full_rental") -> HoldResult:
        """§121 treatments: "full_rental" → no exclusion; "within_3yr" → full
        exclusion (years<=SELL_SOON_MAX_YEARS only); "move_back" → prorated."""
        p = self.p
        future_value = p.home_value * (1 + appr) ** years
        _, remaining = self.principal_paid_over(years)
        sale_costs = future_value * SALE_COST_RATE
        gross_equity = future_value - remaining - sale_costs

        aftertax_rate = opp_rate * (1 - CAP_GAINS_RATE)
        cash_fv = self.compounded_cash_flow(monthly_rent, years, aftertax_rate)

        accumulated_deprec = self.annual_depreciation * min(years, DEPREC_YEARS)
        recapture = accumulated_deprec * DEPREC_RECAPTURE_RATE
        suspended_loss = self.suspended_operating_losses(monthly_rent, years)
        deprec_release = suspended_loss * MARGINAL_TAX

        appreciation_gain = max(0.0, future_value - p.cost_basis)
        if sec121 == "within_3yr" and years <= SELL_SOON_MAX_YEARS:
            excluded = min(CG_EXCLUSION, appreciation_gain)
        elif sec121 == "move_back":
            residence_yrs = p.years_owned_as_residence + MOVE_BACK_YEARS
            total_yrs = p.years_owned_as_residence + years + MOVE_BACK_YEARS
            qualified_fraction = min(1.0, residence_yrs / total_yrs)
            excluded = min(CG_EXCLUSION, appreciation_gain * qualified_fraction)
        else:
            excluded = 0.0
        taxable_gain = max(0.0, appreciation_gain - excluded)
        cap_gains_tax = taxable_gain * CAP_GAINS_RATE

        reserve_opp_cost = p.cash_reserve * ((1 + aftertax_rate) ** years - 1)

        net_worth = (gross_equity + cash_fv + deprec_release
                     - recapture - cap_gains_tax - reserve_opp_cost)
        return HoldResult(future_value, remaining, sale_costs, gross_equity,
                          cash_fv, deprec_release, recapture, appreciation_gain,
                          excluded, cap_gains_tax, reserve_opp_cost, net_worth)

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
            rin, mout, opex, taxb, net = self.oop_breakdown(r)
            rent_rows[r] = {
                "rent_obj": asdict(rr),
                "oop": {"rent_in": rin, "mortgage_out": mout, "opex_out": opex,
                        "tax_back": taxb, "net_year": net, "net_month": net / MONTHS_PER_YEAR},
            }

        hold_grid = {}
        for sec in ("full_rental", "within_3yr", "move_back"):
            hold_grid[sec] = {}
            for label, appr in APPRECIATION.items():
                hold_grid[sec][label] = {
                    rent: [asdict(self.hold_net_worth(rent, y, appr, sec121=sec)) for y in H]
                    for rent in p.rent_levels
                }

        sell_grid = {f"{int(r*100)}%": [self.invest_net_worth(np_, y, r) for y in H]
                     for r in INVEST_RATES}
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
            1 for r in p.realistic_rents for y in H
            if self.hold_net_worth(r, y, PRIMARY_APPRECIATION).net_worth > self.best_sell(y)
        )
        total_cells = len(p.realistic_rents) * len(H)

        weh = WORKED_EXAMPLE_HORIZON
        cum_oop_10 = sum(
            -(self.calc_rent(p.primary_rent * (1 + RENT_GROWTH) ** yr, year_index=yr).cash_flow
              + self.annual_deprec_shield - self.expected_risk_drag)
            for yr in range(weh))
        yr1_oop = -self.oop_breakdown(p.primary_rent)[4]
        yr10_oop = -(self.calc_rent(p.primary_rent * (1 + RENT_GROWTH) ** (weh - 1),
                                    year_index=weh - 1).cash_flow
                     + self.annual_deprec_shield - self.expected_risk_drag)

        base = self.oop_breakdown(p.primary_rent)[4]
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
                "home_value": p.home_value, "cost_basis": p.cost_basis,
                "mortgage_bal": p.mortgage_bal, "monthly_pi": p.monthly_pi,
                "apr": self.apr, "property_tax": p.property_tax, "insurance": p.insurance,
                "repairs": p.repairs, "vacancy_rate": VACANCY_RATE, "mgmt_rate": MGMT_RATE,
                "rent_growth": RENT_GROWTH, "property_tax_growth": PROPERTY_TAX_GROWTH,
                "expense_growth": EXPENSE_GROWTH, "marginal_tax": MARGINAL_TAX,
                "cap_gains_rate": CAP_GAINS_RATE, "deprec_recapture_rate": DEPREC_RECAPTURE_RATE,
                "sale_cost_rate": SALE_COST_RATE, "cg_exclusion": CG_EXCLUSION,
                "invest_rates": INVEST_RATES, "primary_invest": PRIMARY_INVEST,
                "aftertax_opp": AFTERTAX_OPP, "cash_reserve": p.cash_reserve,
                "annual_depreciation": self.annual_depreciation,
                "expected_risk_drag": self.expected_risk_drag,
                "excess_vacancy_months": self.excess_vacancy_months,
                "bad_vacancy_months": BAD_VACANCY_MONTHS, "eviction_cost": EVICTION_COST,
                "major_repair": MAJOR_REPAIR, "years_owned_residence": p.years_owned_as_residence,
                "appreciation": APPRECIATION, "primary_appreciation": PRIMARY_APPRECIATION,
                "horizons": H, "rent_levels": p.rent_levels,
                "realistic_rents": p.realistic_rents, "primary_rent": p.primary_rent,
            },
            "sell": asdict(sell),
            "rent_rows": rent_rows,
            "hold_grid": hold_grid,
            "sell_grid": sell_grid,
            "best_sell_by_horizon": best_sell_by_h,
            "worked_example": asdict(we),
            "risk": risk,
            "verdict": {
                "h10": h10, "h20": h20,
                "best_sell_10": self.best_sell(10), "best_sell_20": self.best_sell(20),
                "verb_10": _compare(h10, self.best_sell(10)),
                "verb_20": _compare(h20, self.best_sell(20)),
                "hold_low_long": hold_low_long, "hold_central_long": hold_central_long,
                "hold_high_long": hold_high_long, "sell_long": sell_long,
                "verb_low_long": _compare(hold_low_long, sell_long),
                "upside": hold_high_long - sell_long,
                "central_edge": hold_central_long - sell_long,
                "downside": hold_low_long - sell_long,
                "win_cells": win_cells, "total_cells": total_cells,
                "longest_horizon": hz,
                "cum_oop_10": cum_oop_10, "yr1_oop": yr1_oop, "yr10_oop": yr10_oop,
                "mo_oop": yr1_oop / MONTHS_PER_YEAR,
                "reserve_cost_yr": p.cash_reserve * AFTERTAX_OPP,
            },
        }


def _compare(hold_v: float, sell_v: float) -> str:
    diff = hold_v - sell_v
    if abs(diff) < 0.03 * sell_v:
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
