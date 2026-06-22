#!/usr/bin/env python3
"""
model.py — PURE MATH for the rent-vs-sell analysis.

No presentation here. A Model wraps one Property (per-house inputs from a TOML) plus
the shared assumptions in assumptions.py, derives the mortgage rate / depreciation /
risk drag once, and exposes the calculations + a compute() that bundles every result
into a plain dict (the contract consumed by render.py).

The comparison is apples-to-apples:
  • HOLD subtracts selling costs AND capital-gains tax at the FUTURE sale.
  • HOLD's negative cash flow is carried forward the SAME way the SELL proceeds are —
    grown at the pre-tax rate with the gain taxed once at liquidation; the reserve at
    the bond rate. Both sides use one investment rule (see compounded_cash_flow).
  • SELL proceeds are compounded and the investment gain is taxed at liquidation.

The generated report is DATA ONLY (figures + mechanic explanations); it contains no
interpretation/verdict. compute() likewise returns facts, not a beats/trails call.

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
    DEPREC_YEARS,
    MARGINAL_TAX,
    NIIT_RATE,
    DEPREC_RECAPTURE_RATE,
    CAP_GAINS_RATE,
    CG_EXCLUSION,
    SELL_SOON_MAX_YEARS,
    PASSIVE_LOSS_USABLE_YEARLY,
    PASSIVE_LOSS_MAGI_LIMIT,
    BAD_VACANCY_MONTHS,
    EVICTION_COST,
    MAJOR_REPAIR,
    RISK_VACANCY_PROB,
    RISK_EVICTION_PROB,
    RISK_REPAIR_PROB,
    RESERVE_RATE,
    BROKER_RATE,
    TRANSFER_TAX,
    TITLE_ESCROW,
    SALE_COST_RATE,
    INVEST_RATES,
    PRIMARY_INVEST,
    APPRECIATION,
    PRIMARY_APPRECIATION,
    HORIZONS,
    WORKED_EXAMPLE_HORIZON,
    MONTHS_PER_YEAR,
    INFLATION_RATE,
)


@dataclass
class Sell:
    price: float
    broker: float
    transfer: float
    title: float
    total_costs: float
    payoff: float
    net_proceeds: float  # cash in hand BEFORE cap-gains tax (the audit breakdown's subtotal)
    capital_gain: float
    tax: float  # cap-gains tax owed at closing on a gain ($0 on a loss)
    net_after_tax: float  # net_proceeds − tax: the amount actually available to invest


@dataclass
class Rent:
    monthly_rent: float
    gross: float
    vacancy: float
    egi: float
    mgmt: float
    leasing: float
    prop_tax: float  # property tax component of fixed_costs
    other_fixed: float  # insurance + repairs component of fixed_costs
    fixed_costs: float  # = prop_tax + other_fixed
    op_expenses: float
    noi: float
    annual_pi: float
    cash_flow: float


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

    Validates that the payment can actually amortize the loan: at r→0 the payment is the
    principal-only floor balance/n, so a pmt at or below that has no positive note rate —
    a sign of an inconsistent input (a stale/typo'd monthly_pi vs. mortgage_bal/
    payments_left). Without this guard the bisection drives r toward 0, where (1+r)^−n
    underflows to 1.0 and the denominator hits exactly 0 → an opaque ZeroDivisionError deep
    in Model.__init__. A clear ValueError at the source is far easier to act on.
    """
    if balance > 0 and pmt <= balance / n:
        raise ValueError(
            f"monthly_pi ({pmt:,.2f}) is too small to amortize mortgage_bal ({balance:,.2f}) "
            f"over payments_left ({n}): it must exceed the principal-only floor "
            f"{balance / n:,.2f}/mo. Check the property TOML for a stale or mistyped payment."
        )
    lo, hi = 0.0, 0.02
    for _ in range(200):
        r = (lo + hi) / 2
        calc = balance * r / (1 - (1 + r) ** -n) if r > 0 else balance / n
        if calc > pmt:
            hi = r
        else:
            lo = r
    return r


def excluded_gain(treatment: Sec121, appreciation_gain: float, years: int) -> float:
    """How much of the future capital gain the §121 exclusion shelters, in dollars.

    Rule (IRC §121): up to CG_EXCLUSION of gain on a primary residence is tax-free if
    you owned AND used it as your main home ≥2 of the last 5 years before sale. A pure
    rental fails the use test entirely. The two treatments model the realistic options:

      FULL_RENTAL  → rented continuously, never re-occupied: fails the use test, $0 excluded.
      WITHIN_3YR   → sold soon enough that the 2-of-5 test is still met (only valid up to
                     SELL_SOON_MAX_YEARS of renting): full exclusion, capped at CG_EXCLUSION.

    (A "move back in to re-qualify" scenario is intentionally NOT modeled: re-occupying
    for a couple of years to reclaim a prorated exclusion only earns the tax benefit if
    you ALSO bear the offsetting cost — years of forgone rent and your own housing cost
    over an extended timeline — which more than cancels the benefit for this property.
    Modeling only the benefit would overstate it, so the scenario is omitted rather than
    half-modeled.)

    Returns a non-negative dollar amount, never exceeding the gain or the statutory cap.
    """
    if treatment == Sec121.WITHIN_3YR and years <= SELL_SOON_MAX_YEARS:
        return min(CG_EXCLUSION, appreciation_gain)
    return 0.0  # FULL_RENTAL, or WITHIN_3YR past the eligibility window


@dataclass
class SaleTax:
    """The three taxes triggered when a held rental is finally sold."""

    recapture: float  # depreciation recapture (a cost, positive number)
    deprec_release: float  # suspended passive losses freed at sale (a benefit, positive)
    cap_gains_tax: float  # tax on appreciation above basis, net of §121 (a cost, positive)
    excluded_gain: float  # §121 exclusion applied (for display/audit)
    appreciation_gain: float  # gain above original cost basis, pre-§121 (for display/audit)


def tax_at_sale(
    accumulated_deprec: float,
    suspended_loss: float,
    realized_amount: float,
    cost_basis: float,
    treatment: Sec121,
    years: int,
) -> SaleTax:
    """All taxes that land at the future sale of a property held as a rental.

    `realized_amount` is the sale price NET of selling costs (the §1001 amount realized);
    `cost_basis` is the ORIGINAL (pre-depreciation) basis. Adjusted basis = cost_basis −
    accumulated_deprec. The total recognized gain (realized − adjusted basis) splits into
    two slices that this function taxes separately:

      • RECAPTURE (unrecaptured §1250 gain): the part of the recognized gain attributable
        to depreciation taken, taxed at DEPREC_RECAPTURE_RATE (fed §1250 25% + NIIT 3.8% +
        CA ordinary 13.3% — it IS net investment income for a high-MAGI owner, so it
        carries NIIT just like the cap-gains slice does). A cost.
        CAP (IRC §1250/§1(h)): unrecaptured §1250 gain cannot exceed the TOTAL recognized
        gain. So recapture is charged on min(accumulated_deprec, realized − adjusted_basis),
        not on all depreciation taken. When the property sells above its original cost
        basis this min() is the full depreciation (the historical common case); when it
        sells BETWEEN adjusted basis and cost basis only the smaller recognized gain is
        recaptured; below adjusted basis it's a §1231 loss and recapture is $0.

      • DEPREC_RELEASE: for a high-MAGI owner, yearly rental losses are *suspended*
        (no annual deduction) and released all at once at sale, deductible at the
        ordinary MARGINAL_TAX rate → a benefit. suspended_loss is the accumulated loss.
        (If PASSIVE_LOSS_USABLE_YEARLY, suspended_loss is 0 because it was used yearly.)
        NOTE: recapture and release only PARTIALLY offset — recapture accrues on all
        depreciation taken, while the released loss pool is drawn down once the rental
        turns tax-positive in later years, so they do not cancel over a long hold.

      • CAP_GAINS_TAX: the appreciation above original cost basis (the recognized gain
        in EXCESS of the recaptured §1250 slice), minus any §121 exclusion, taxed at
        CAP_GAINS_RATE (fed LT 20% + NIIT 3.8% + CA 13.3%). A cost. Floored at 0 — a
        sale below cost basis produces no cap-gains slice (and a sale below adjusted
        basis is a §1231 loss this model conservatively does not credit).

    All amounts are positive dollars; signs are applied by the caller. Rates are flat
    effective rates — a simplification; real brackets are graduated.
    """
    adjusted_basis = cost_basis - accumulated_deprec
    recognized_gain = realized_amount - adjusted_basis
    # §1250 cap: recapture only the depreciation that is actually recovered by the gain.
    recapture_base = max(0.0, min(accumulated_deprec, recognized_gain))
    recapture = recapture_base * DEPREC_RECAPTURE_RATE
    deprec_release = suspended_loss * MARGINAL_TAX
    # Cap-gains slice = recognized gain ABOVE original cost basis (i.e. above the part
    # already taxed as §1250 recapture). Equivalent to max(0, realized − cost_basis).
    appreciation_gain = max(0.0, realized_amount - cost_basis)
    excluded = excluded_gain(treatment, appreciation_gain, years)
    # max(0,…) is defensive: excluded_gain already caps at min(CG_EXCLUSION, gain), so the
    # difference is never negative in practice. The floor just guarantees a §121 exclusion
    # can never turn into a tax CREDIT if that capping ever changed.
    taxable_gain = max(0.0, appreciation_gain - excluded)
    # CAP_GAINS_RATE bundles NIIT (3.8%). Applying it to the POST-exclusion gain is
    # correct, NOT a bug: §121-excluded gain is excluded from gross income, and NIIT
    # only reaches net investment income that IS in gross income — so the excluded slice
    # rightly escapes NIIT too. (Depreciation recapture is separate above and is never
    # §121-excludable, which the code already respects.)
    cap_gains_tax = taxable_gain * CAP_GAINS_RATE
    return SaleTax(recapture, deprec_release, cap_gains_tax, excluded, appreciation_gain)


class Model:
    """One property's rent-vs-sell analysis. Per-property inputs come from `prop`;
    shared market/tax assumptions are module-level imports. Derived per-property
    values (mortgage rate, depreciation, expected risk drag) are computed once here."""

    def __init__(self, prop: Property, rent_growth: float = RENT_GROWTH):
        self.p = prop
        # Rent-growth rate is an instance attribute (defaults to the shared assumption)
        # so a sensitivity can build a second Model at a different rate without mutating
        # globals — see compute()'s rent_growth_sensitivity.
        self.rent_growth = rent_growth
        # Derived mortgage figures
        self.monthly_rate = _derive_monthly_rate(
            prop.mortgage_bal, prop.monthly_pi, prop.payments_left
        )
        self.apr = self.monthly_rate * MONTHS_PER_YEAR
        # Derived depreciation: straight-line over 27.5 yrs on the building only (land
        # is not depreciable). `building_basis` is set per-property as the lower of cost
        # or FMV at conversion (IRC §168(i)(5)) times the land/building split from a
        # credible appraisal — see the property TOML. NOTE on precision: depreciation has
        # two opposing tax effects at sale — it's recaptured at DEPREC_RECAPTURE_RATE
        # (~38%) AND it creates suspended losses released at MARGINAL_TAX (~40%). These
        # only PARTIALLY offset: recapture grows with all accumulated depreciation, while
        # the suspended-loss pool plateaus/shrinks once the rental turns tax-positive in
        # later years (interest-only deductibility). So the net is a real cost at long
        # holds, not a wash — building_basis precision matters more than "they cancel."
        self.annual_depreciation = prop.building_basis / DEPREC_YEARS
        self.annual_deprec_shield = (
            self.annual_depreciation * MARGINAL_TAX if PASSIVE_LOSS_USABLE_YEARLY else 0.0
        )
        # A major repair (roof/foundation/sewer lateral) is a CAPITAL IMPROVEMENT, not a
        # deductible expense: it's added to basis, so it reduces the taxable gain at sale.
        # Its NET economic cost is therefore the cash outlay less the basis-driven tax
        # recovery ≈ MAJOR_REPAIR × (1 − CAP_GAINS_RATE). (Depreciation taken on the
        # improvement during the hold is itself recaptured at sale, so it roughly washes
        # and isn't modeled separately.) Simplification, but far closer than expensing the
        # full $40k. Eviction costs and lost rent ARE ordinary deductible expenses, but for
        # a high-MAGI owner those losses are suspended (see suspended_operating_losses),
        # so they're carried here at full cash cost.
        self.net_major_repair = MAJOR_REPAIR * (1 - CAP_GAINS_RATE)
        # Expected annual risk drag (vacancy term counts only EXCESS beyond baseline)
        self.excess_vacancy_months = BAD_VACANCY_MONTHS - MONTHS_PER_YEAR * VACANCY_RATE
        self.expected_risk_drag = (
            RISK_VACANCY_PROB * (self.excess_vacancy_months * prop.primary_rent)
            + RISK_EVICTION_PROB * EVICTION_COST
            + RISK_REPAIR_PROB * self.net_major_repair
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
        the two agree, which guards against an off-by-one or sign error in the loop.

        Floored at 0, matching the iterative schedule's `bal<=0` payoff guard: a balance
        can't go negative (the loan is simply gone). Without the floor a payment that
        slightly over-amortizes — or any inconsistent payment-vs-balance input — would yield
        a spurious negative balance that the looped version (which stops at payoff) never
        produces, breaking their agreement."""
        r = self.monthly_rate
        k = min(years * MONTHS_PER_YEAR, self.p.payments_left)
        if r == 0:
            return max(0.0, self.p.mortgage_bal - self.p.monthly_pi * k)
        growth = (1 + r) ** k
        return max(0.0, self.p.mortgage_bal * growth - self.p.monthly_pi * (growth - 1) / r)

    # ── Sell today ────────────────────────────────────────────────────────────
    def calc_sell(self) -> Sell:
        p = self.p
        broker = p.home_value * BROKER_RATE
        transfer = p.home_value * TRANSFER_TAX
        title = p.home_value * TITLE_ESCROW
        total = broker + transfer + title
        net = p.home_value - total - p.mortgage_bal
        # Taxable gain is the AMOUNT REALIZED (price net of selling costs) minus basis
        # (IRC §1001/§1016 — selling expenses reduce the amount realized). Negative => loss.
        gain = (p.home_value - total) - p.cost_basis
        tax = 0.0 if gain <= CG_EXCLUSION else (gain - CG_EXCLUSION) * CAP_GAINS_RATE
        # The cap-gains tax is OWED AT CLOSING, so only net_proceeds − tax is actually
        # available to invest on the SELL side. Charging it here keeps the comparison
        # symmetric: the HOLD path likewise pays its cap-gains tax at the future sale
        # (hold_net_worth subtracts st.cap_gains_tax). Investing the pre-tax proceeds would
        # overstate SELL — money owed the IRS can't also compound in the market. (On a loss,
        # tax is 0, so net_after_tax == net_proceeds; harold-ave sells at a loss.)
        net_after_tax = net - tax
        return Sell(
            p.home_value,
            broker,
            transfer,
            title,
            total,
            p.mortgage_bal,
            net,
            gain,
            tax,
            net_after_tax,
        )

    # ── Rent (year-1 economics; year_index inflates fixed costs) ───────────────
    def _pi_months_in_year(self, year_index: int) -> int:
        """How many monthly P&I payments are actually made during year `year_index`.

        The mortgage ends after `payments_left` payments (≈ year payments_left/12). Years
        fully inside the term pay 12; the year the loan is retired pays the partial
        remainder; every year AFTER payoff pays 0. Without this the cash-flow model would
        keep subtracting a full year's P&I forever — a silent drain on a loan that no
        longer exists, which understates the hold path at horizons past payoff. Returns an
        int in [0, 12]. (Whole-month granularity; a mid-month payoff isn't modeled — the
        P&I is level, so a fractional final month is immaterial next to the headline.)
        """
        months_before = year_index * MONTHS_PER_YEAR
        remaining = self.p.payments_left - months_before
        return max(0, min(MONTHS_PER_YEAR, remaining))

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
        # P&I for ONLY the months the loan is still active this year — after payoff the
        # property carries no mortgage and the cash flow turns strongly positive (the loan
        # is gone, rent keeps coming). See _pi_months_in_year.
        annual_pi = p.monthly_pi * self._pi_months_in_year(year_index)
        cash_flow = noi - annual_pi
        return Rent(
            monthly_rent,
            gross,
            vacancy,
            egi,
            mgmt,
            leasing,
            prop_tax,
            other_fixed,
            fixed,
            op,
            noi,
            annual_pi,
            cash_flow,
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

    def risk_scenarios(self, monthly_rent: float) -> dict:
        """Bad-year cash scenarios at `monthly_rent` (year-1). One source for both the
        report's bad-year table and its JS live mirror. Each event is the INCREMENTAL cost
        added to the normal-year out-of-pocket baseline; rows stand alone (they don't add).
        The worst case stacks all three in one year — independent and individually unlikely
        (probabilities in assumptions.py), so a deliberately pessimistic tail. The major
        repair is carried at its NET (post-tax-recovery) cost (it's a capital improvement,
        added to basis). All figures signed: outflows negative.

        VACANCY CONVENTION: the incremental vacancy hit charges only the EXCESS months over
        the baseline (excess_vacancy_months = BAD_VACANCY_MONTHS − the normal vacancy already
        netted into `base` via the 5% VACANCY_RATE) — the SAME convention as
        expected_risk_drag, so the bad-year table and the risk drag don't double-count the
        baseline vacancy."""
        base = self.oop_breakdown(monthly_rent).net
        extra_vacancy_cost = self.excess_vacancy_months * monthly_rent
        worst_extra = extra_vacancy_cost + EVICTION_COST + self.net_major_repair
        return {
            "baseline": base,
            "extra_vacancy": -extra_vacancy_cost,
            "eviction": -EVICTION_COST,
            "major_repair": -self.net_major_repair,
            "major_repair_gross": -MAJOR_REPAIR,
            "worst_extra": -worst_extra,
            "worst_total": base - worst_extra,
            "worst_case_is_compound": True,
        }

    # ── Multi-year hold ────────────────────────────────────────────────────────
    def _year_cash_flow(self, monthly_rent: float, year_index: int) -> float:
        """One year's ECONOMIC cash flow for the hold path (the money the property
        actually puts in / takes out of your pocket that year). Single definition,
        consumed by compounded_cash_flow and by the out-of-pocket figures in compute()
        so they can never drift apart. Sign: a drain is negative.

          = rental cash flow (NOI − full P&I; usually negative)
            + annual depreciation tax shield (0 here — passive losses are suspended)
            − expected risk drag (probability-weighted vacancy/eviction/repair cost)

        `year_index` inflates rent (RENT_GROWTH) and fixed costs (in calc_rent).
        """
        rent_this_yr = monthly_rent * (1 + self.rent_growth) ** year_index
        return (
            self.calc_rent(rent_this_yr, year_index=year_index).cash_flow
            + self.annual_deprec_shield
            - self.expected_risk_drag
        )

    def _taxable_rental_income(
        self, monthly_rent: float, year_index: int, interest_yr: float
    ) -> float:
        """One year's TAXABLE rental income = rent − op-ex − mortgage INTEREST −
        depreciation. (Only interest is deductible, not principal; depreciation stops
        after the 27.5-yr recovery period.) Negative => a tax loss that year. Distinct
        from _year_cash_flow, which is ECONOMIC cash (uses full P&I, no depreciation).

        Depreciation runs straight-line for exactly DEPREC_YEARS (27.5) — NOT 27.5 *whole*
        years. Total deductible depreciation can never exceed building_basis. With integer
        year indices, `year_index < 27.5` would grant a FULL 28th year (indices 0..27),
        depreciating ~half a year's worth ($9,782 here) MORE than basis — a deduction with
        no basis behind it, and one the recapture cap (which tops out at min(years, 27.5))
        would never claw back. So the final year carries only its FRACTIONAL remainder:
        full deduction for indices 0..26, half a year at index 27, $0 after — summing to
        exactly 27.5 × annual = building_basis, in lockstep with the recapture cap."""
        rent_this_yr = monthly_rent * (1 + self.rent_growth) ** year_index
        r = self.calc_rent(rent_this_yr, year_index=year_index)
        deprec_yrs_this_year = max(0.0, min(1.0, DEPREC_YEARS - year_index))
        deprec = self.annual_depreciation * deprec_yrs_this_year
        return r.egi - r.op_expenses - interest_yr - deprec

    def _profit_year_taxes(self, monthly_rent: float, years: int) -> list[float]:
        """Per-year income tax owed on PROFITABLE rental years, as a list aligned to
        years 0..years-1 (each a non-negative cost).

        Under high MAGI, yearly losses are suspended into a §469 pool (see
        suspended_operating_losses). Once the rental turns tax-positive, that profit is
        first absorbed by the pool (no tax) and only the EXCESS over the remaining pool is
        taxed — at the ordinary marginal rate plus NIIT, since net rental income is passive
        investment income. (If passive losses are usable yearly, there is no pool and
        profits are taxed in full as they arise.)
        """
        schedule = self.amortization_schedule(years)
        pool = 0.0
        taxes = []
        for yr in range(years):
            ti = self._taxable_rental_income(monthly_rent, yr, schedule[yr][0])
            if ti < 0:
                if not PASSIVE_LOSS_USABLE_YEARLY:
                    pool += -ti  # suspend the loss
                taxes.append(0.0)
            else:
                taxable = ti
                if not PASSIVE_LOSS_USABLE_YEARLY:
                    absorbed = min(pool, ti)  # prior suspended losses shelter the profit
                    pool -= absorbed
                    taxable = ti - absorbed
                taxes.append(taxable * (MARGINAL_TAX + NIIT_RATE))
        return taxes

    def compounded_cash_flow(self, monthly_rent: float, years: int, pretax_rate: float) -> float:
        """FV at the horizon of every year's hold cash flow, carried forward the SAME
        way the SELL path's proceeds are: grown at the PRE-TAX `pretax_rate`, with only
        the investment GAIN taxed once at liquidation (CAP_GAINS_RATE).

        Why pre-tax-grow-then-tax-the-gain instead of a flat after-tax rate: the SELL
        side (invest_net_worth) gets tax-DEFERRED compounding — its money grows untaxed
        and is taxed once at the end. To compare apples-to-apples, the money you instead
        feed the property each year must be charged that same opportunity: had you not
        spent it, it would have compounded pre-tax and been taxed once. A flat annual
        after-tax rate would tax it every year and understate the true opportunity cost,
        unfairly favoring HOLD. The transform below is algebraically identical to
        invest_net_worth's (verified), so both sides use one investment rule.

        Each year's cash flow is the ECONOMIC cash flow LESS any income tax owed on a
        profitable rental year (see _profit_year_taxes — zero while the property runs at
        a tax loss, which is every year for a typical high-leverage hold). Works for
        negative cash flow (a drain): only the gain portion is taxed, so an outflow is
        carried forward as outflow + after-tax forgone growth.
        """
        profit_taxes = self._profit_year_taxes(monthly_rent, years)
        fv = 0.0
        for yr in range(years):
            cf = self._year_cash_flow(monthly_rent, yr) - profit_taxes[yr]
            growth = (1 + pretax_rate) ** (years - yr - 1)
            fv += cf * (1 + (growth - 1) * (1 - CAP_GAINS_RATE))
        return fv

    def suspended_operating_losses(self, monthly_rent: float, years: int) -> float:
        """The suspended passive-loss CARRYFORWARD pool released at sale (§469).
        Positive number; $0 if passive losses are usable yearly.

        Each year's rental tax result = rent − op-ex − mortgage INTEREST − depreciation
        (only INTEREST is deductible, not principal — so we pull per-year interest from
        the shared amortization schedule). Under high MAGI the annual loss can't offset
        wages; it's suspended and carried forward.

        §469 mechanic: the carryforward is a running POOL — loss years add to it, and
        later PROFITABLE years draw it back down (passive income absorbs prior suspended
        losses), floored at 0. Only what survives to the sale is released. (Summing loss
        years alone would ignore that profitable later years consume the pool, overstating
        the release benefit — ~$30k at 20yr for this property.)
        """
        if PASSIVE_LOSS_USABLE_YEARLY:
            return 0.0
        pool = 0.0
        schedule = self.amortization_schedule(years)
        for yr in range(years):
            taxable_income = self._taxable_rental_income(monthly_rent, yr, schedule[yr][0])
            # Negative income grows the pool; positive income (passive) draws it down.
            pool = max(0.0, pool - taxable_income)
        return pool

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
        `opp_rate` is the PRE-tax investment rate. Both the cash drain and the idle
        reserve are charged the SAME investment rule as the SELL side: grow pre-tax,
        tax the gain once at liquidation (see compounded_cash_flow) — so the two sides
        are genuinely symmetric, not one taxed annually and the other taxed once.
        """
        p = self.p

        # Equity at the future sale: home grown at `appr`, less the loan still owed,
        # less the cost to sell (same SALE_COST_RATE we'd pay selling today — counted
        # here too so the hold side isn't unfairly spared the eventual transaction cost).
        future_value = p.home_value * (1 + appr) ** years
        _, remaining = self.principal_paid_over(years)
        sale_costs = future_value * SALE_COST_RATE
        gross_equity = future_value - remaining - sale_costs

        # Cash flow is money you feed the property; it can't also be invested. It's
        # charged the SELL side's opportunity rule (grow pre-tax at opp_rate, tax the
        # gain once) — see compounded_cash_flow for why this, not a flat after-tax rate.
        cash_fv = self.compounded_cash_flow(monthly_rent, years, opp_rate)

        # Taxes triggered at the sale (recapture, released suspended losses, cap gains).
        # Depreciation stops accruing after the 27.5-yr schedule ends, hence the min().
        accumulated_deprec = self.annual_depreciation * min(years, DEPREC_YEARS)
        suspended_loss = self.suspended_operating_losses(monthly_rent, years)
        # The AMOUNT REALIZED is the future price net of selling costs (IRC §1001 —
        # selling costs reduce the amount realized). tax_at_sale splits the gain over
        # adjusted basis into the §1250-recapture slice (capped at the recognized gain)
        # and the cap-gains slice, so it needs the realized amount and the ORIGINAL basis.
        realized_amount = future_value - sale_costs
        st = tax_at_sale(
            accumulated_deprec,
            suspended_loss,
            realized_amount,
            p.cost_basis,
            sec121,
            years,
        )

        # Reserve opportunity cost = the SPREAD you give up by holding. A landlord reserve
        # must stay liquid/safe, so while holding it earns the short-term bond rate
        # (RESERVE_RATE), whereas if you'd sold, that same cash could go into the market at
        # opp_rate. The cost is the difference in growth, on the symmetric grow-then-tax-
        # the-gain-once basis (only the gain is taxed, hence ×(1−CG)). Charged to hold only
        # — the sell path needs no landlord reserve.
        opp_growth = (1 + opp_rate) ** years
        bond_growth = (1 + RESERVE_RATE) ** years
        reserve_opp_cost = p.cash_reserve * (opp_growth - bond_growth) * (1 - CAP_GAINS_RATE)

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
            st.appreciation_gain,
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
        np_ = self.calc_sell().net_after_tax  # invest AFTER the closing cap-gains tax
        return max(self.invest_net_worth(np_, years, r) for r in INVEST_RATES)

    def hold_then_invest_net_worth(
        self,
        monthly_rent: float,
        sell_year: int,
        horizon: int,
        appr: float,
        opp_rate: float = PRIMARY_INVEST,
        sec121: Sec121 = Sec121.FULL_RENTAL,
    ) -> float:
        """Wealth at `horizon` years if you HOLD (rent it out) until `sell_year`, sell, then
        invest the proceeds at the market rate for the remaining years.

        This puts the HOLD path on the SAME footing as SELL-now as a function of CALENDAR
        time: both are "your wealth in year t under one rule — invest at the market rate once
        your money is liquid." Before sell_year you're still holding (the value IS
        hold_net_worth at that point); at/after sell_year you've converted to cash and it
        compounds like the sell side.

        hold_net_worth(sell_year) is already AFTER-tax (the year-`sell_year` sale's costs and
        cap-gains/recapture are paid in it), so the post-sale leg taxes only the INCREMENTAL
        market gains earned from sell_year→horizon — exactly invest_net_worth's
        grow-pre-tax-tax-the-gain-once rule, identical to how SELL-now's proceeds are taxed.
        So Hold-sold-at-S and Sell-now are directly comparable (the reader can stack them).

        At sell_year == 0 this reduces to investing the just-sold hold value (≡ the SELL-now
        construction at the same appreciation-independent proceeds — a built-in sanity check).
        When the horizon is at or BEFORE the sell year you haven't sold yet, so it's just the
        hold value AT THE HORIZON (still a rental). A negative net worth (underwater early)
        compounds like any principal in invest_net_worth (a shortfall carried at the market rate).
        """
        # Before (or at) the sell year you're still holding — the value is the hold value at
        # the horizon, not yet converted to cash.
        if horizon <= sell_year:
            return self.hold_net_worth(
                monthly_rent, horizon, appr, opp_rate=opp_rate, sec121=sec121
            ).net_worth
        # Sold at sell_year (value already after-tax), then invested to the horizon — only the
        # incremental market gains are taxed again (invest_net_worth's grow-then-tax-once rule).
        nw_at_sale = self.hold_net_worth(
            monthly_rent, sell_year, appr, opp_rate=opp_rate, sec121=sec121
        ).net_worth
        return self.invest_net_worth(nw_at_sale, horizon - sell_year, opp_rate)

    def break_even_appreciation(self, years: int, opp_rate: float = PRIMARY_INVEST) -> float:
        """The home-appreciation rate at which HOLD net worth equals SELL net worth at
        `years`, with BOTH sides compounding at the same `opp_rate` (so the only thing
        being solved for is appreciation, not an opportunity-rate mismatch). A neutral
        FACT, not a recommendation: it tells the reader how much appreciation the hold
        needs to break even, leaving them to judge how likely that is (and to fold in
        their own risk tolerance — wanting margin above break-even is a risk view).

        hold_net_worth is monotonically increasing in appreciation (test_higher_appr...),
        so we bisect on appr in [−10%, +25%]/yr. Both sides use opp_rate: HOLD via its
        cash-flow/reserve opportunity cost, SELL via invest_net_worth at the same rate.
        Returns the break-even appreciation as a rate (e.g. 0.0325). If hold never reaches
        sell within the bracket, returns the bracket endpoint (won't happen in practice).
        """
        target = self.invest_net_worth(self.calc_sell().net_after_tax, years, opp_rate)
        lo, hi = -0.10, 0.25
        for _ in range(100):
            mid = (lo + hi) / 2
            nw = self.hold_net_worth(self.p.primary_rent, years, mid, opp_rate=opp_rate).net_worth
            if nw < target:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    def js_params(self) -> dict:
        """Every constant + per-property field the browser-side JS engine
        (static/model.js) needs, as plain numbers — so the JS NEVER hardcodes a value
        Python owns (CLAUDE.md rule 3). render injects this as `const PARAMS = {...}`.

        Deliberately NOT part of compute()'s returned dict (so the golden snapshot stays
        a pure record of the financial RESULTS, not the JS plumbing): render calls this
        directly. static/model.js is a deliberate, TESTED mirror of this model's math (the
        one sanctioned exception to the no-JS rule, for the interactive break-even
        explorer); tests/test_js_model.py pins the JS output to Python within $1. If you
        add an input the JS math reads, add it here too, or the JS silently goes stale.
        """
        p = self.p
        return {
            # per-property inputs
            "home_value": p.home_value,
            "cost_basis": p.cost_basis,
            "building_basis": p.building_basis,
            "mortgage_bal": p.mortgage_bal,
            "monthly_pi": p.monthly_pi,
            "payments_left": p.payments_left,
            "property_tax": p.property_tax,
            "insurance": p.insurance,
            "repairs": p.repairs,
            "primary_rent": p.primary_rent,
            "cash_reserve": p.cash_reserve,
            # derived
            "monthly_rate": self.monthly_rate,
            # shared market/tax/policy constants
            "rent_growth": RENT_GROWTH,
            "property_tax_growth": PROPERTY_TAX_GROWTH,
            "expense_growth": EXPENSE_GROWTH,
            "vacancy_rate": VACANCY_RATE,
            "mgmt_rate": MGMT_RATE,
            "tenancy_years": TENANCY_YEARS,
            "leasing_fee_months": LEASING_FEE_MONTHS,
            "months_per_year": MONTHS_PER_YEAR,
            "deprec_years": DEPREC_YEARS,
            "marginal_tax": MARGINAL_TAX,
            "niit_rate": NIIT_RATE,
            "deprec_recapture_rate": DEPREC_RECAPTURE_RATE,
            "cap_gains_rate": CAP_GAINS_RATE,
            "cg_exclusion": CG_EXCLUSION,
            "sell_soon_max_years": SELL_SOON_MAX_YEARS,
            "passive_loss_usable_yearly": PASSIVE_LOSS_USABLE_YEARLY,
            "passive_loss_magi_limit": PASSIVE_LOSS_MAGI_LIMIT,
            "reserve_rate": RESERVE_RATE,
            "bad_vacancy_months": BAD_VACANCY_MONTHS,
            "eviction_cost": EVICTION_COST,
            "major_repair": MAJOR_REPAIR,
            "risk_vacancy_prob": RISK_VACANCY_PROB,
            "risk_eviction_prob": RISK_EVICTION_PROB,
            "risk_repair_prob": RISK_REPAIR_PROB,
            "broker_rate": BROKER_RATE,
            "transfer_tax": TRANSFER_TAX,
            "title_escrow": TITLE_ESCROW,
            "sale_cost_rate": SALE_COST_RATE,
            "invest_rates": list(INVEST_RATES),
            "primary_invest": PRIMARY_INVEST,
            "primary_appreciation": PRIMARY_APPRECIATION,
            "horizons": list(HORIZONS),
        }

    # ── Compute: bundle everything into a plain dict ───────────────────────────
    def compute(self) -> dict:
        """Bundle every computed result into one plain dict — the contract render.py
        consumes, and (dumped to output/model_output.json) a standalone AUDIT artifact.

        Note on scope: render.py reads the headline figures, the sensitivity blocks,
        risk, and cash_facts; the full grids below (hold_grid across every §121 treatment
        × appreciation × rent, sell_grid, rent_rows) are produced deliberately for the
        audit JSON and the golden-snapshot test — they let a CPA inspect/diff every cell
        even though the report shows only a slice. They are intentional, not dead code;
        keep them in sync with the snapshot (run `make snapshot` after an intended
        numeric change).
        """
        p = self.p
        sell = self.calc_sell()
        np_ = sell.net_after_tax  # SELL invests proceeds net of the closing cap-gains tax
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

        # Rent-growth sensitivity: rent growth is the single largest swing factor in the
        # hold case, and the base 3% (recent SF ZORI) sits well below the 4.85% home
        # appreciation. Rather than pick one, show the hold outcome (primary rent, central
        # appreciation) at BOTH the base rate and a "rent tracks home value" rate so the
        # reader sees the range. The high-rate Model reuses the same property; only
        # rent_growth differs (no global mutation).
        rg_low = RENT_GROWTH
        rg_high = PRIMARY_APPRECIATION  # rent grows as fast as the house ("they re-couple")
        m_high_rg = Model(p, rent_growth=rg_high)
        rent_growth_sensitivity = {
            "rg_low": rg_low,
            "rg_high": rg_high,
            "rows": {
                y: {
                    "low": self.hold_net_worth(p.primary_rent, y, PRIMARY_APPRECIATION).net_worth,
                    "high": m_high_rg.hold_net_worth(
                        p.primary_rent, y, PRIMARY_APPRECIATION
                    ).net_worth,
                    "best_sell": self.best_sell(y),
                }
                for y in H
            },
        }

        # Opportunity-rate sensitivity: the rate at which BOTH sides compound is applied
        # to different principal amounts — the sell side compounds the (smaller) cash
        # proceeds, while the hold side applies it to the cash-flow stream and reserve
        # against a leveraged asset — so the two sides' net-worth figures respond
        # differently to it. Report both at each INVEST_RATES level (same rate on both
        # sides, central appreciation, primary rent); the reader compares.
        opp_rate_sensitivity = {
            "rates": list(INVEST_RATES),
            "rows": {
                y: {
                    f"{int(r * 100)}%": {
                        "hold": self.hold_net_worth(
                            p.primary_rent, y, PRIMARY_APPRECIATION, opp_rate=r
                        ).net_worth,
                        "sell": self.invest_net_worth(np_, y, r),
                    }
                    for r in INVEST_RATES
                }
                for y in H
            },
        }

        # Break-even appreciation: the home-appreciation rate at which HOLD ties SELL at
        # each horizon, both sides at the primary opp rate. A single neutral FACT per
        # horizon that lets the reader weigh the decision against their own appreciation
        # belief (and their own risk margin) — stated alongside the scenario rates so the
        # cushion above/below break-even is visible. opp_rate is pinned for comparability.
        break_even = {
            "opp_rate": PRIMARY_INVEST,
            "scenarios": dict(APPRECIATION),
            "primary": PRIMARY_APPRECIATION,
            "rows": {y: self.break_even_appreciation(y) for y in H},
        }

        hz = max(H)

        # Wealth-over-CALENDAR-TIME chart series: both curves are "your wealth in year t" under
        # ONE rule (invest at the market rate once liquid). SELL sold at year 0; HOLD holds
        # until the chosen sell year then invests the proceeds at the market rate (see
        # hold_then_invest_net_worth). Both move with all slider axes (appreciation, rent
        # growth, market return) AND the sell-year slider — so dragging any shifts the crossing.
        # Data only — render plots these points; it labels no side as "winning".
        #
        # The mortgage pays off at payments_left/12 years; past that the HOLD curve bends
        # (P&I drops to 0). We surface the payoff year so the chart can mark it. The sell year
        # is also surfaced so the chart can mark where HOLD switches from property to market.
        sell_year = WORKED_EXAMPLE_HORIZON  # the seed/default S (the slider drives it live)
        year_grid = list(range(0, hz + 1))  # 0..hz inclusive, yearly steps
        chart_hold = [
            self.hold_then_invest_net_worth(p.primary_rent, sell_year, y, PRIMARY_APPRECIATION)
            for y in year_grid
        ]
        # SELL at the SINGLE primary market rate (not best_sell's max-over-INVEST_RATES):
        # the live chart's market-return slider IS this rate, so the server-seeded curve must
        # use one rate too, or the static first-paint would disagree with the JS redraw. At
        # the base case PRIMARY_INVEST is the top INVEST_RATE, so the two coincide there.
        chart_sell = [self.invest_net_worth(np_, y, PRIMARY_INVEST) for y in year_grid]
        # Crossover year: the first year where sign(HOLD − SELL) differs from year 1's sign.
        # A neutral fact (when the two lines meet), not a verdict about which is preferable.
        diffs = [h - s for h, s in zip(chart_hold, chart_sell)]
        crossover_year = None
        if len(diffs) > 1:
            sign1 = 1 if diffs[1] >= 0 else -1
            for y in range(2, len(diffs)):
                cur = 1 if diffs[y] >= 0 else -1
                if cur != sign1:
                    crossover_year = y
                    break
        payoff_year = p.payments_left / MONTHS_PER_YEAR
        break_even_chart = {
            "horizon": hz,
            "year_grid": year_grid,
            "hold": chart_hold,
            "sell": chart_sell,
            "crossover_year": crossover_year,
            "payoff_year": payoff_year,
            "sell_year": sell_year,
        }

        # Per-year CASH-FLOW chart: the HOLD path's actual economic cash flow each year (rent
        # − operating costs − P&I that year + deprec shield − risk drag), which is what hits
        # the bank account. It's a deep drain early (rent doesn't cover the mortgage) and
        # flips POSITIVE once the loan is paid off — surfacing the "you're FUNDING this, not
        # harvesting it" fact that the net-worth chart buries inside cash_flow_fv. The SELL
        # path has NO yearly cash flow: the proceeds are reinvested and compound untouched,
        # nothing is withdrawn — so its line is a flat $0 (stored once for the renderer).
        # Data only — render plots these; it draws no conclusion. year_index 0..hz-1 (a cash
        # flow is a flow DURING a year, so the last plotted year is hz−1, unlike the
        # net-worth chart whose points are end-of-year stocks at 0..hz).
        cashflow_years = list(range(0, hz))
        cashflow_hold = [self._year_cash_flow(p.primary_rent, y) for y in cashflow_years]
        cashflow_chart = {
            "year_grid": cashflow_years,
            "hold": cashflow_hold,
            "sell": 0.0,  # reinvested proceeds throw off no withdrawn cash flow
            "payoff_year": payoff_year,
        }

        we = self.hold_net_worth(p.primary_rent, WORKED_EXAMPLE_HORIZON, PRIMARY_APPRECIATION)
        # What a dollar at the longest horizon is worth in today's purchasing power,
        # derived from INFLATION_RATE so the report's "worth ~X today" line can never
        # drift from the constant (CLAUDE.md rule 3). Purely a reader aid — the model is
        # nominal throughout and never discounts internally.
        today_value_fraction = 1.0 / (1.0 + INFLATION_RATE) ** hz

        weh = WORKED_EXAMPLE_HORIZON
        cum_oop_10 = sum(-self._year_cash_flow(p.primary_rent, yr) for yr in range(weh))
        yr1_oop = -self.oop_breakdown(p.primary_rent).net
        yr10_oop = -self._year_cash_flow(p.primary_rent, weh - 1)

        # Bad-year scenarios at the primary rent (the method is the single source, also
        # mirrored in static/model.js for the live table). See Model.risk_scenarios.
        risk = self.risk_scenarios(p.primary_rent)

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
                "reserve_rate": RESERVE_RATE,
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
            "rent_growth_sensitivity": rent_growth_sensitivity,
            "opp_rate_sensitivity": opp_rate_sensitivity,
            "break_even": break_even,
            "break_even_chart": break_even_chart,
            "cashflow_chart": cashflow_chart,
            "worked_example": asdict(we),
            "risk": risk,
            # Neutral cash FACTS only — out-of-pocket figures used by the report. The
            # net-worth numbers themselves live in hold_grid / sell_grid /
            # best_sell_by_horizon and the sensitivity blocks; this section deliberately
            # holds NO beats/trails comparison, edge, or win-count — those are
            # interpretation, produced downstream, not here.
            "cash_facts": {
                "longest_horizon": hz,
                "shortest_horizon": min(H),
                "inflation_rate": INFLATION_RATE,
                "today_value_fraction": today_value_fraction,
                "cum_oop_10": cum_oop_10,
                "yr1_oop": yr1_oop,
                "yr10_oop": yr10_oop,
                "mo_oop": yr1_oop / MONTHS_PER_YEAR,
                # One-year reserve drag: the after-tax spread between the market rate and
                # the bond rate the reserve actually earns (consistent with reserve_opp_cost).
                "reserve_cost_yr": p.cash_reserve
                * (PRIMARY_INVEST - RESERVE_RATE)
                * (1 - CAP_GAINS_RATE),
            },
        }


def _main():
    import os
    import sys

    if len(sys.argv) < 2:
        sys.exit("usage: python model.py properties/<file>.toml  (the Makefile owns the default)")
    path = sys.argv[1]
    model = Model(load_property(path))
    os.makedirs("output", exist_ok=True)
    with open("output/model_output.json", "w") as f:
        json.dump(model.compute(), f, indent=2)
    print(f"[output/model_output.json written for {path}]")


if __name__ == "__main__":
    _main()
