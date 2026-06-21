#!/usr/bin/env python3
"""
assumptions.py — SHARED, reusable model assumptions (market + tax + policy).

These are NOT specific to one house: tax rates, SF market appreciation/rent growth,
risk probabilities, opportunity-cost, sale-cost rates, §121 rules. Per-property
inputs (value, basis, loan, rents, reserve, dates) live in properties/*.toml and
are loaded via load_property(). model.py combines a Property with these assumptions.

To analyze a different house: copy a properties/*.toml and edit it — leave this file
alone unless the market/tax assumptions themselves change (e.g. a non-SF metro).

Provenance: the appreciation and rent-growth figures were derived (once, by hand)
from Zillow's SF series — ZHVI (home values → Case-Shiller-style appreciation CAGRs)
and ZORI (observed rents → RENT_GROWTH). They are PINNED here, not recomputed at
runtime, so the model is deterministic.

Every rate carries a one-line rationale so a CPA can audit it.
"""

import tomllib
from dataclasses import dataclass
from enum import Enum


class Sec121(str, Enum):
    """How the §121 primary-residence capital-gains exclusion is treated at the
    FUTURE sale. (str-Enum so it serializes cleanly to JSON.)"""

    FULL_RENTAL = "full_rental"  # rented the whole time, never re-occupy → no exclusion
    WITHIN_3YR = "within_3yr"  # sell while still passing the 2-of-5-yr test → full exclusion


# ── PER-PROPERTY INPUTS (loaded from properties/*.toml) ───────────────────────


@dataclass
class Property:
    address: str
    as_of_date: str
    home_value: float
    cost_basis: float
    building_basis: float
    mortgage_bal: float
    monthly_pi: float
    payments_left: int
    years_owned_as_residence: float
    property_tax: float
    insurance: float
    repairs: float
    rent_levels: list[float]
    realistic_rents: list[float]
    primary_rent: float
    cash_reserve: float


def load_property(path: str) -> Property:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return Property(**data)


# ── Rental assumptions (market) ───────────────────────────────────────────────
PROPERTY_TAX_GROWTH = 0.02  # Prop 13 caps assessed-value growth at 2%/yr
EXPENSE_GROWTH = 0.03  # insurance + repairs grow ~CPI
VACANCY_RATE = 0.05  # typical SF
MGMT_RATE = 0.06  # property management on collected rent
TENANCY_YEARS = 2.0  # avg tenant stay; leasing fee amortized over this
LEASING_FEE_MONTHS = 1.0  # tenant-placement fee = 1 month's rent per turnover
RENT_GROWTH = 0.03  # SF ZORI history (2.7% 10-yr); decoupled from appr.

MONTHS_PER_YEAR = 12

# ── Tax-rate components (each real-world rate defined ONCE, composed below) ────
FED_LT_CAP_GAINS = 0.20  # federal long-term capital-gains rate
NIIT_RATE = 0.038  # net investment income tax
CA_TOP_RATE = 0.133  # CA top marginal (no preferential LT rate)
FED_RECAPTURE = 0.25  # federal unrecaptured §1250 max
MARGINAL_TAX = 0.40  # combined fed+CA ORDINARY rate (single, >$250k income)
INCOME_BRACKET_THRESHOLD = 250_000  # income level justifying MARGINAL_TAX (display)
PASSIVE_LOSS_MAGI_LIMIT = 150_000  # MAGI above which passive losses suspend

# Unrecaptured §1250 gain is net investment income for a high-MAGI owner, so it carries
# NIIT too (consistent with CAP_GAINS_RATE): fed §1250 25% + NIIT 3.8% + CA ordinary 13.3%.
DEPREC_RECAPTURE_RATE = FED_RECAPTURE + NIIT_RATE + CA_TOP_RATE
CAP_GAINS_RATE = FED_LT_CAP_GAINS + NIIT_RATE + CA_TOP_RATE
CG_EXCLUSION = 250_000  # §121 primary-residence exclusion (single filer)
# The §121 "use" test (occupy 2 of the last 5 yrs) is encoded operationally by
# SELL_SOON_MAX_YEARS below — that's the max rental period where the test still passes.
SELL_SOON_MAX_YEARS = 3  # max hold where "sell soon" still passes the 2-of-5 test
# MAGI > limit → passive rental losses suspended, released at sale (no yearly shield)
PASSIVE_LOSS_USABLE_YEARLY = False

# ── Depreciation ──────────────────────────────────────────────────────────────
# The depreciable building basis (cost/value excluding non-depreciable land) is a
# PER-PROPERTY input — see Property.building_basis in the TOML, since the land/building
# split differs per house. Only the recovery period is shared:
DEPREC_YEARS = 27.5  # residential rental straight-line

# ── Risk (landlord buffer + bad-year events) ──────────────────────────────────
# The landlord reserve amount is PER-PROPERTY (Property.cash_reserve in the TOML),
# sized to cover a realistic bad year. It must stay liquid and safe, so it earns the
# short-term bond rate below — NOT the 7% stock rate. The opportunity cost of holding
# it is therefore only the SPREAD between the two (see hold_net_worth.reserve_opp_cost).
RESERVE_RATE = 0.03  # short-term bonds / T-bills — where a liquid reserve realistically sits
BAD_VACANCY_MONTHS = 3  # vacancy in a bad year
EVICTION_COST = 12_000  # legal + lost rent during SF eviction
MAJOR_REPAIR = 40_000  # roof / foundation / sewer lateral, etc.
# Annual probability of each bad-year event over a long hold (for expected drag):
RISK_VACANCY_PROB = 0.15  # ~1 long vacancy every ~7 yrs
RISK_EVICTION_PROB = 0.05  # ~1 eviction every ~20 yrs
RISK_REPAIR_PROB = 0.10  # ~1 big repair every ~10 yrs

# ── Sale costs (% of sale price; applied to a sale today AND a future sale) ────
BROKER_RATE = 0.05  # 2.5% listing + 2.5% buyer agent (negotiable)
TRANSFER_TAX = 0.0068  # SF transfer tax, $1M–$5M band
TITLE_ESCROW = 0.0075  # title/escrow/recording/misc
SALE_COST_RATE = BROKER_RATE + TRANSFER_TAX + TITLE_ESCROW  # ~6.43%

# ── Investing the sale proceeds / opportunity cost ────────────────────────────
INVEST_RATES = [0.05, 0.07]  # conservative / S&P long-run nominal
PRIMARY_INVEST = INVEST_RATES[1]  # pre-tax rate, used for BOTH paths' compounding (7%)
# Both paths compound PRE-TAX at PRIMARY_INVEST and tax the gain once at the end
# (see model.compounded_cash_flow) — not a flat after-tax rate, which would tax the
# opportunity every year and unfairly favor HOLD.

# ── Appreciation scenarios (S&P Case-Shiller SF, FRED SFXRSA, latest 2026-03) ─
#   2.5% = 20-yr CAGR (peak-to-now), 4.85% = 10-yr CAGR, 6% ≈ 30-yr full cycle.
#   Keys are clean labels; the percent text shown to users is derived from the value.
APPRECIATION = {"low": 0.025, "moderate": 0.0485, "high": 0.06}
# Source note per scenario (Case-Shiller window), shown in the sensitivity table:
APPRECIATION_NOTES = {"low": "SF 20-yr", "moderate": "SF 10-yr", "high": "SF 30-yr"}
APPRECIATION_TAGS = {"low": "pessimistic", "moderate": "primary", "high": "optimistic"}
PRIMARY_APPRECIATION = APPRECIATION["moderate"]

HORIZONS = [3, 5, 10, 15, 20]  # years
WORKED_EXAMPLE_HORIZON = 10  # horizon featured in the "how a number is built" example
