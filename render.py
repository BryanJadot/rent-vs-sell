#!/usr/bin/env python3
"""
render.py — PRESENTATION ONLY for the rent-vs-sell analysis.

Pulls every number from model.compute() and the model's calc functions, builds the
HTML table rows, and renders templates/ into output/. Also writes a plain-text summary.
No financial math lives here — if a number looks wrong, fix model.py; if a value looks
wrong, fix assumptions.py.

Generated output is DATA ONLY: figures, sensitivities, and explanations of how each
number is built (terms/mechanics). It contains NO interpretation — no verdict, no
recommendation, no "which is better". Interpretation is produced by a separate prompt
downstream so it isn't anchored by conclusions baked in here. See CLAUDE.md.

Run:  python3 render.py   (or: make report)
"""

import json
import math
import os
import sys

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from assumptions import (
    load_property,
    Sec121,
    PRIMARY_APPRECIATION,
    APPRECIATION,
    HORIZONS,
    WORKED_EXAMPLE_HORIZON,
    INVEST_RATES,
    RENT_GROWTH,
    MARGINAL_TAX,
    CAP_GAINS_RATE,
    DEPREC_RECAPTURE_RATE,
    SALE_COST_RATE,
    BROKER_RATE,
    TRANSFER_TAX,
    TITLE_ESCROW,
    FED_LT_CAP_GAINS,
    NIIT_RATE,
    CA_TOP_RATE,
    FED_RECAPTURE,
    PRIMARY_INVEST,
    RESERVE_RATE,
    BAD_VACANCY_MONTHS,
    EVICTION_COST,
    MAJOR_REPAIR,
    RISK_VACANCY_PROB,
    RISK_EVICTION_PROB,
    RISK_REPAIR_PROB,
    SELL_SOON_MAX_YEARS,
    VACANCY_RATE,
    MGMT_RATE,
    TENANCY_YEARS,
    LEASING_FEE_MONTHS,
    CG_EXCLUSION,
    PASSIVE_LOSS_MAGI_LIMIT,
    INCOME_BRACKET_THRESHOLD,
    MONTHS_PER_YEAR,
)
from model import Model

OUTDIR = "output"

# Break-even chart geometry — ONE definition, shared by the server-rendered SVG
# (_break_even_svg) and the live JS redraw (injected as `CHART` so static/model.js never
# retypes these — CLAUDE.md rule 3). viewBox units; margins leave room for axis labels.
CHART_W, CHART_HH = 640, 340
CHART_ML, CHART_MR, CHART_MT, CHART_MB = 64, 16, 34, 40
CHART_STEP = 500_000.0  # round $0.5M gridline spacing on the value axis

# ── Small HTML row builders (return Markup so Jinja won't re-escape) ──────────


def _nw_row(label_html, values, cls="", bold_last=False):
    cells = ""
    for i, v in enumerate(values):
        inner = f"<b>{v:,.0f}</b>" if (bold_last and i == len(values) - 1) else f"{v:,.0f}"
        cells += f"<td>{inner}</td>"
    return f'<tr class="{cls}"><td>{label_html}</td>{cells}</tr>'


def _break_even_svg(chart: dict) -> str:
    """Inline SVG of HOLD and SELL wealth over calendar time (X = years). The two curves
    cross at the crossover year. Drawing only — every number comes from compute()'s
    break_even_chart; this does no financial math, just coordinate mapping. Strictly DATA:
    two plain curves, a marked crossing, dashed ticks at the mortgage-payoff and chosen-sell
    years. NO shading or labeling of a side as better — that would be a verdict (CLAUDE.md
    rule 2). The JS buildSvg mirrors this layout.
    """
    grid = chart["year_grid"]
    hold = chart["hold"]
    sell = chart["sell"]
    crossover = chart["crossover_year"]
    payoff = chart["payoff_year"]
    sell_year = chart["sell_year"]

    # Plot box (viewBox units) — geometry lives in the module CHART_* constants so the live
    # JS redraw uses the identical box (CLAUDE.md rule 3).
    W, Hh = CHART_W, CHART_HH
    ml, mr, mt, mb = CHART_ML, CHART_MR, CHART_MT, CHART_MB
    x0, x1 = ml, W - mr
    y0, y1 = Hh - mb, mt  # y0 = bottom (pixel), y1 = top

    ax_min, ax_max = grid[0], grid[-1]  # year domain (0..horizon)
    # Snap the value axis to round $0.5M gridlines so the labels read cleanly and the
    # spacing is even. y_min/y_max become multiples of the step.
    raw_lo = min(min(hold), min(sell))
    raw_hi = max(max(hold), max(sell))
    step = CHART_STEP
    y_min = math.floor(raw_lo / step) * step
    y_max = math.ceil(raw_hi / step) * step
    if y_max == y_min:  # degenerate guard
        y_max = y_min + step

    def px(t):  # year -> x pixel
        return x0 + (t - ax_min) / (ax_max - ax_min) * (x1 - x0)

    def py(v):  # dollars -> y pixel
        return y0 + (v - y_min) / (y_max - y_min) * (y1 - y0)

    hold_pts = " ".join(f"{px(t):.1f},{py(v):.1f}" for t, v in zip(grid, hold))
    sell_pts = " ".join(f"{px(t):.1f},{py(v):.1f}" for t, v in zip(grid, sell))

    cross_phrase = (
        f"the two curves cross around year {crossover}"
        if crossover is not None
        else "the two curves do not cross over the years shown"
    )
    parts = [
        f'<svg viewBox="0 0 {W} {Hh}" role="img" '
        f'aria-label="Hold and sell wealth over time, in years; {cross_phrase}." '
        'style="width:100%;height:auto;font:12px system-ui,sans-serif">'
    ]

    # Axes
    parts.append(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y0}" stroke="#bbb"/>')
    parts.append(f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}" stroke="#bbb"/>')

    # Y gridlines + $ labels at every round $0.5M step (even, clean values)
    n_steps = round((y_max - y_min) / step)
    for i in range(n_steps + 1):
        v = y_min + i * step
        yy = py(v)
        parts.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}" stroke="#eee"/>')
        m_val = v / 1e6
        label = f"−${abs(m_val):.1f}M" if m_val < 0 else f"${m_val:.1f}M"
        parts.append(
            f'<text x="{x0 - 6}" y="{yy + 4:.1f}" text-anchor="end" fill="#666">{label}</text>'
        )

    # X ticks every 5 years across the domain
    t = ax_min
    while t <= ax_max + 1e-9:
        xx = px(t)
        parts.append(
            f'<text x="{xx:.1f}" y="{y0 + 18}" text-anchor="middle" fill="#666">{t:g}</text>'
        )
        t += 5

    # Mortgage-payoff reference tick — explains the kink where P&I drops to 0.
    if ax_min <= payoff <= ax_max:
        xx = px(payoff)
        parts.append(
            f'<line x1="{xx:.1f}" y1="{y0}" x2="{xx:.1f}" y2="{y1}" '
            'stroke="#cdd6e5" stroke-dasharray="3 3"/>'
        )
        parts.append(
            f'<text x="{xx:.1f}" y="{y1 - 10:.1f}" text-anchor="middle" fill="#90a">'
            f"loan paid off ~{payoff:.0f}y</text>"
        )

    # Sell-year tick — where HOLD switches from property to invested cash (the curve bends).
    # Drawn distinctly from the payoff reference so it reads as the chosen action.
    if ax_min < sell_year < ax_max:
        xx = px(sell_year)
        parts.append(
            f'<line x1="{xx:.1f}" y1="{y0}" x2="{xx:.1f}" y2="{y1}" '
            'stroke="#c9a0d8" stroke-dasharray="2 2"/>'
        )
        parts.append(
            f'<text x="{xx:.1f}" y="{y0 + 32:.1f}" text-anchor="middle" fill="#a05fc0">'
            f"sold yr {sell_year}</text>"
        )

    # The two data series (both curves)
    parts.append(f'<polyline points="{sell_pts}" fill="none" stroke="#2a7" stroke-width="2"/>')
    parts.append(f'<polyline points="{hold_pts}" fill="none" stroke="#36c" stroke-width="2"/>')

    # Crossover point, if any (where the two curves meet). Linear-interpolate the y between
    # the bracketing yearly samples so the dot sits on the lines, not at the integer year.
    if crossover is not None and ax_min <= crossover <= ax_max:
        cx = px(crossover)
        cy = py((hold[crossover] + sell[crossover]) / 2)
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" fill="#111"/>')
        parts.append(
            f'<text x="{cx:.1f}" y="{cy - 10:.1f}" text-anchor="middle" fill="#111">'
            f"cross ~yr {crossover}</text>"
        )

    # Inline series labels at the RIGHT edge of each curve (they fan apart by the horizon).
    parts.append(
        f'<text x="{x1 - 6}" y="{py(hold[-1]) - 8:.1f}" text-anchor="end" fill="#36c">Hold</text>'
    )
    parts.append(
        f'<text x="{x1 - 6}" y="{py(sell[-1]) + 16:.1f}" text-anchor="end" fill="#2a7">Sell now</text>'
    )

    # Axis title
    parts.append(
        f'<text x="{(x0 + x1) / 2:.0f}" y="{Hh - 4}" text-anchor="middle" fill="#444">Year</text>'
    )

    parts.append("</svg>")
    return "".join(parts)


# Cash-flow chart geometry: a separate value-axis step ($25k) since per-year cash flows are
# tens of thousands, not the millions of the net-worth chart. One definition, shared with JS.
CASHFLOW_STEP = 25_000.0


def _cashflow_svg(chart: dict) -> str:
    """Inline SVG of the HOLD path's per-year economic cash flow over the holding period
    (X = years). It crosses $0: a drain early (rent doesn't cover the mortgage), turning
    positive once the loan is paid off. SELL is a flat $0 line (proceeds reinvested, nothing
    withdrawn). Drawing only — numbers come from compute()'s cashflow_chart; no financial
    math here, just coordinate mapping. DATA only: two plain lines, a zero baseline, a
    payoff tick. No labeling of a side as better (CLAUDE.md rule 2). JS mirrors this layout.
    """
    grid = chart["year_grid"]
    hold = chart["hold"]
    payoff = chart["payoff_year"]

    W, Hh = CHART_W, CHART_HH
    ml, mr, mt, mb = CHART_ML, CHART_MR, CHART_MT, CHART_MB
    x0, x1 = ml, W - mr
    y0, y1 = Hh - mb, mt

    ax_min, ax_max = grid[0], grid[-1]
    step = CASHFLOW_STEP
    # Include 0 in the value range so the baseline is always on-screen.
    raw_lo = min(min(hold), 0.0)
    raw_hi = max(max(hold), 0.0)
    y_min = math.floor(raw_lo / step) * step
    y_max = math.ceil(raw_hi / step) * step
    if y_max == y_min:
        y_max = y_min + step

    def px(t):
        return x0 + (t - ax_min) / (ax_max - ax_min) * (x1 - x0)

    def py(v):
        return y0 + (v - y_min) / (y_max - y_min) * (y1 - y0)

    hold_pts = " ".join(f"{px(t):.1f},{py(v):.1f}" for t, v in zip(grid, hold))
    zero_y = py(0.0)
    parts = [
        f'<svg viewBox="0 0 {W} {Hh}" role="img" '
        'aria-label="Hold per-year cash flow over the holding period; negative early, '
        'turning positive after the mortgage is paid off; the sell line is flat at zero." '
        'style="width:100%;height:auto;font:12px system-ui,sans-serif">'
    ]
    # Axes
    parts.append(f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}" stroke="#bbb"/>')

    # Y gridlines + $ labels at every step (signed, in $k)
    n_steps = round((y_max - y_min) / step)
    for i in range(n_steps + 1):
        v = y_min + i * step
        yy = py(v)
        parts.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}" stroke="#eee"/>')
        k = v / 1000
        label = f"−${abs(k):.0f}k" if k < 0 else f"${k:.0f}k"
        parts.append(
            f'<text x="{x0 - 6}" y="{yy + 4:.1f}" text-anchor="end" fill="#666">{label}</text>'
        )

    # X ticks every 5 years
    t = ax_min
    while t <= ax_max + 1e-9:
        parts.append(
            f'<text x="{px(t):.1f}" y="{y0 + 18}" text-anchor="middle" fill="#666">{t:g}</text>'
        )
        t += 5

    # Mortgage-payoff tick — the cash flow jumps up here as P&I ends.
    if ax_min <= payoff <= ax_max:
        xx = px(payoff)
        parts.append(
            f'<line x1="{xx:.1f}" y1="{y0}" x2="{xx:.1f}" y2="{y1}" '
            'stroke="#cdd6e5" stroke-dasharray="3 3"/>'
        )
        parts.append(
            f'<text x="{xx:.1f}" y="{y1 - 10:.1f}" text-anchor="middle" fill="#90a">'
            f"loan paid off ~{payoff:.0f}y</text>"
        )

    # Zero baseline = the SELL line (flat $0, proceeds reinvested) AND the cash-flow axis.
    parts.append(
        f'<line x1="{x0}" y1="{zero_y:.1f}" x2="{x1}" y2="{zero_y:.1f}" '
        'stroke="#2a7" stroke-width="2"/>'
    )
    # Hold cash-flow line
    parts.append(f'<polyline points="{hold_pts}" fill="none" stroke="#36c" stroke-width="2"/>')

    parts.append(
        f'<text x="{x0 + 6}" y="{py(hold[0]) + 16:.1f}" text-anchor="start" fill="#36c">Hold</text>'
    )
    parts.append(
        f'<text x="{x1 - 6}" y="{zero_y - 8:.1f}" text-anchor="end" fill="#2a7">Sell now ($0)</text>'
    )
    parts.append(
        f'<text x="{(x0 + x1) / 2:.0f}" y="{Hh - 4}" text-anchor="middle" fill="#444">'
        "Years held (per-year cash in/out of pocket)</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


def _cashflow_table_html(m: Model, rent: float) -> str:
    """Year-1 cash-in/out breakdown at one rent — the server seed for the live table
    (#be-cashflow-table-live). Single rent column (the rent slider drives it live). Every
    number comes from the model's calc_rent / oop_breakdown; render only arranges and signs.
    Mirrored by static/model.js buildCashflowTable.
    """
    oop = m.oop_breakdown(rent)
    rt = m.calc_rent(rent)
    # (label, signed value). Outflows negative; the model owns the figures.
    rows = [
        ("Rent collected (net of vacancy)", oop.rent_in),
        ("Mortgage payment (principal &amp; interest)", oop.mortgage_out),
        ("Property tax", -rt.prop_tax),
        ("Insurance", -m.p.insurance),
        ("Repairs / maintenance", -m.p.repairs),
        ("Management &amp; leasing", -(rt.mgmt + rt.leasing)),
        (
            f"Yearly depreciation tax break "
            f'<span class="sub">(none now — suspended at income &gt;${PASSIVE_LOSS_MAGI_LIMIT / 1000:g}k, used at sale; see §3)</span>',
            oop.tax_back,
        ),
    ]
    body = ""
    for label, v in rows:
        if v == 0:
            cell = '<td class="sub">$0</td>'
        else:
            cls = "num-good" if v > 0 else "num-bad"
            sign = "+" if v > 0 else "−"
            cell = f'<td class="{cls}">{sign}{abs(v):,.0f}</td>'
        body += f"<tr><td>{label}</td>{cell}</tr>"
    net = oop.net
    net_sign = "+" if net >= 0 else "−"
    body += (
        f'<tr class="total"><td>Net cash flow / yr</td>'
        f'<td class="num-bad">{net_sign}{abs(net):,.0f}</td></tr>'
        f'<tr class="total"><td>…per month</td>'
        f'<td class="num-bad">{net_sign}{abs(net) / MONTHS_PER_YEAR:,.0f}</td></tr>'
    )
    return f"<thead><tr><th>Cash item (at ${rent / 1000:g}k/mo)</th><th>Year 1</th></tr></thead><tbody>{body}</tbody>"


def _badyear_table_html(m: Model, rent: float) -> str:
    """Bad-year cost table at one rent — server seed for the live table
    (#be-badyear-table-live). Uses Model.risk_scenarios (one math source). Mirrored by
    static/model.js buildBadYearTable.

    Structure deliberately avoids a running-total column: each bad event shows only its OWN
    extra cost on top of the normal year (the events are independent — they don't stack or
    sum down a column). The baseline and the all-three-at-once worst case are stated as
    their own framed rows so nothing reads as a column sum.
    """
    r = m.risk_scenarios(rent)
    events = [
        ("A long vacancy (above normal turnover)", r["extra_vacancy"]),
        ("A non-paying tenant + eviction", r["eviction"]),
        ("A major repair (roof/foundation), net of tax", r["major_repair"]),
    ]
    body = (
        f"<tr><td>A <b>normal</b> year already costs</td>"
        f'<td class="num-bad">−{abs(r["baseline"]):,.0f}</td></tr>'
        f'<tr><td colspan="2" class="sub">Any <b>one</b> bad event that year adds, on its own '
        f"(they don't stack):</td></tr>"
    )
    for label, hit in events:
        body += f'<tr><td>&nbsp;&nbsp;{label}</td><td class="num-bad">−{abs(hit):,.0f}</td></tr>'
    body += (
        f'<tr class="total"><td>All <b>three</b> at once → that year costs</td>'
        f'<td class="num-bad">−{abs(r["worst_total"]):,.0f}</td></tr>'
    )
    return (
        f"<thead><tr><th>At ${rent / 1000:g}k/mo</th><th>Out of pocket</th></tr></thead>"
        f"<tbody>{body}</tbody>"
    )


def build_context(m: Model) -> dict:
    p = m.p
    sell = m.calc_sell()
    H = HORIZONS
    computed = m.compute()  # one call; index the slices below (compute() is the contract)

    # Live net-worth chart seed (the static sensitivity tables it used to sit beside —
    # headline, by-appreciation, rent-growth, market-return, break-even — are subsumed by
    # the sliders + the live horizon table, so they're gone). Numbers come from compute().
    be_chart_svg = _break_even_svg(computed["break_even_chart"])

    # Server-rendered seed for the live horizon table, at the base-case slider defaults
    # (PRIMARY_APPRECIATION / RENT_GROWTH / PRIMARY_INVEST / default sell year). Identical
    # layout to the JS buildHorizonTable so the static fallback (no-JS / print / first paint)
    # matches what the slider shows. HOLD = hold-then-invest at the default sell year (same
    # wealth-over-time basis as the chart). Numbers come from the model; render arranges them.
    seed_sell_year = computed["break_even_chart"]["sell_year"]
    be_tbl_head = "".join(f"<th>{y}-yr</th>" for y in H)

    def _seed_hold(y):
        return m.hold_then_invest_net_worth(
            p.primary_rent, seed_sell_year, y, PRIMARY_APPRECIATION, opp_rate=PRIMARY_INVEST
        )

    be_tbl_hold = "".join(f"<td>{_seed_hold(y):,.0f}</td>" for y in H)
    be_tbl_sell = "".join(
        f"<td>{m.invest_net_worth(sell.net_after_tax, y, PRIMARY_INVEST):,.0f}</td>" for y in H
    )
    be_tbl_gap = ""
    for y in H:
        d = _seed_hold(y) - m.invest_net_worth(sell.net_after_tax, y, PRIMARY_INVEST)
        sign = "+" if d >= 0 else "−"
        be_tbl_gap += f"<td>{sign}{abs(d):,.0f}</td>"
    be_table_seed = (
        f"<thead><tr><th>If you sell in year {seed_sell_year}</th>{be_tbl_head}</tr></thead>"
        f'<tbody><tr class="primary"><td>Hold (keep &amp; rent, then invest)</td>{be_tbl_hold}</tr>'
        f'<tr class="sell"><td>Sell now + invest</td>{be_tbl_sell}</tr>'
        f'<tr class="total"><td>Hold − Sell</td>{be_tbl_gap}</tr></tbody>'
    )

    # Server-rendered seed for the per-year cash-flow chart (base case). JS swaps it live.
    cashflow_svg = _cashflow_svg(computed["cashflow_chart"])

    # Worked example
    we = m.hold_net_worth(p.primary_rent, WORKED_EXAMPLE_HORIZON, PRIMARY_APPRECIATION)

    # Server seeds for the two live §2 tables, at the default (primary) rent. The rent
    # slider redraws them live via static/model.js; these show before JS / in print.
    cashflow_table_seed = _cashflow_table_html(m, p.primary_rent)
    badyear_table_seed = _badyear_table_html(m, p.primary_rent)

    # §121 benefit at a 3-yr hold: how much keeping the exclusion is worth vs. a full rental
    # at the same horizon (a neutral figure for the one-line note in §1). Model owns the math.
    sec121_benefit_3yr = (
        m.hold_net_worth(
            p.primary_rent, SELL_SOON_MAX_YEARS, PRIMARY_APPRECIATION, sec121=Sec121.WITHIN_3YR
        ).net_worth
        - m.hold_net_worth(
            p.primary_rent, SELL_SOON_MAX_YEARS, PRIMARY_APPRECIATION, sec121=Sec121.FULL_RENTAL
        ).net_worth
    )

    # Assumptions table rows. Per-property values from p; shared from assumptions.
    appr_pcts = " / ".join(f"{val * 100:g}%" for val in APPRECIATION.values())
    a = [
        ("Home value", f"${p.home_value:,.0f}", "Zillow Zestimate"),
        ("Cost basis", f"${p.cost_basis:,.0f}", "purchase price"),
        ("Mortgage balance", f"${p.mortgage_bal:,.0f}", "owner figure"),
        (
            "Mortgage rate",
            f"{m.apr * 100:.3f}%",
            f"derived from ${p.monthly_pi:,.2f} P&amp;I + {p.payments_left} payments",
        ),
        ("Property tax", f"${p.property_tax:,.0f}", "actual bill"),
        ("Insurance", f"${p.insurance:,.0f}", "home + umbrella"),
        ("Repairs / maintenance", f"${p.repairs:,.0f}", "year-1 estimate; grows ~CPI"),
        (
            "Rent (realistic)",
            f"${p.realistic_rents[0]:,.0f}–{p.realistic_rents[-1]:,.0f}/mo",
            "local comps",
        ),
        ("Rent growth", f"{RENT_GROWTH * 100:g}%/yr", "SF ZORI history; decoupled from home appr."),
        ("Home appreciation", appr_pcts, "Case-Shiller SF (FRED SFXRSA) 20/10/30-yr CAGR"),
        ("Vacancy", f"{VACANCY_RATE * 100:g}%", "typical SF"),
        (
            "Property management",
            f"{MGMT_RATE * 100:g}% + {LEASING_FEE_MONTHS:g}-mo leasing",
            f"leasing fee amortized over {TENANCY_YEARS:g}-yr tenancy",
        ),
        (
            "Sale costs",
            f"{SALE_COST_RATE * 100:.2f}%",
            f"{BROKER_RATE * 100:g}% broker + {TRANSFER_TAX * 100:g}% transfer + {TITLE_ESCROW * 100:g}% title",
        ),
        (
            "Marginal / ordinary tax",
            f"{MARGINAL_TAX * 100:g}%",
            f"single, &gt;${INCOME_BRACKET_THRESHOLD / 1000:g}k income",
        ),
        (
            "Cap-gains rate (future)",
            f"{CAP_GAINS_RATE * 100:.1f}%",
            f"fed {FED_LT_CAP_GAINS * 100:g}% + NIIT {NIIT_RATE * 100:g}% + CA {CA_TOP_RATE * 100:g}%",
        ),
        (
            "Depreciation recapture",
            f"{DEPREC_RECAPTURE_RATE * 100:.1f}%",
            f"fed {FED_RECAPTURE * 100:g}% + NIIT {NIIT_RATE * 100:g}% + CA {CA_TOP_RATE * 100:g}%",
        ),
        (
            "Passive losses",
            "suspended",
            f"MAGI &gt;${PASSIVE_LOSS_MAGI_LIMIT / 1000:g}k → released at sale",
        ),
        (
            "Investment return (sell)",
            f"{INVEST_RATES[0] * 100:g}% / {INVEST_RATES[1] * 100:g}% pre-tax",
            "conservative / S&amp;P long-run nominal",
        ),
        (
            "Hold opportunity cost",
            f"{PRIMARY_INVEST * 100:g}% pre-tax",
            "neg. cash flow &amp; reserve compounded the SAME as the sell side "
            "(grow pre-tax, tax the gain once) — symmetric",
        ),
        (
            "Expected risk drag",
            f"${m.expected_risk_drag:,.0f}/yr",
            f"prob-weighted: {RISK_VACANCY_PROB * 100:g}%×{m.excess_vacancy_months:.1f}mo excess vacancy + {RISK_EVICTION_PROB * 100:g}%×eviction + {RISK_REPAIR_PROB * 100:g}%×repair",
        ),
        (
            "Bad-year events",
            "vac/evict/repair",
            f"{BAD_VACANCY_MONTHS}mo vacancy, ${EVICTION_COST:,.0f} eviction, ${MAJOR_REPAIR:,.0f} repair "
            f"(capital improvement → ${m.net_major_repair:,.0f} net of tax). Worst case stacks all three.",
        ),
        ("Cash reserve", f"${p.cash_reserve:,.0f}", "landlord buffer estimate"),
        (
            "Reserve return (bonds)",
            f"{RESERVE_RATE * 100:g}%",
            "the reserve must stay liquid/safe, so it earns the short-term bond rate, "
            "not the market — the hold side gives up the spread",
        ),
    ]
    assumption_rows = "".join(
        f'<tr><td>{name}</td><td>{val}</td><td class="sub">{src}</td></tr>' for name, val, src in a
    )

    # Neutral cash facts (out-of-pocket figures) — no interpretation; the report states
    # figures and explains terms but draws no conclusion. See CLAUDE.md.
    v = computed["cash_facts"]

    # ── Interactive break-even explorer payload ───────────────────────────────
    # PARAMS = every constant/per-property number the JS engine reads (Rule 3: single
    # source — js_params() owns them, the JS retypes nothing). CHART = the SAME geometry
    # the server SVG uses. The JS itself is INLINED (read from disk) so the report stays a
    # single openable/emailable file with no external fetch. The model.js engine is a
    # tested mirror of model.py (tests/test_js_model.py) — the one no-JS exception.
    bec = computed["break_even_chart"]
    params_json = json.dumps(m.js_params())
    chart_json = json.dumps(
        {
            "W": CHART_W,
            "Hh": CHART_HH,
            "ml": CHART_ML,
            "mr": CHART_MR,
            "mt": CHART_MT,
            "mb": CHART_MB,
            "step": CHART_STEP,
            "yearGrid": bec["year_grid"],
            "horizon": bec["horizon"],
            "payoffYear": bec["payoff_year"],
            # Per-year cash-flow chart shares the box but uses its own $ step and year grid
            # (cash flows are a flow during years 0..hz-1, not an end-of-year stock at 0..hz).
            "cashflowStep": CASHFLOW_STEP,
            "cashflowYearGrid": computed["cashflow_chart"]["year_grid"],
        }
    )
    with open(os.path.join("static", "model.js")) as f:
        model_js = f.read()
    # Slider defaults = the model's base case; ranges decided tight around realistic SF.
    # Rounded to the slider step (0.1) to avoid float noise like 4.8500000000000005 in the
    # value attribute — the engine still reads the true constant via PARAMS, this is display.
    slider_appr_default = round(PRIMARY_APPRECIATION * 100, 2)
    slider_rent_default = round(RENT_GROWTH * 100, 2)  # rent-GROWTH slider (%/yr)
    slider_market_default = round(PRIMARY_INVEST * 100, 2)
    # Rent-LEVEL slider ($/mo): default is the property's primary rent; range decided
    # $4,000–$6,500 step $250 (spans the comps with room to probe past them).
    slider_rentlevel_default = p.primary_rent
    slider_rentlevel_min = 4000
    slider_rentlevel_max = 6500
    slider_rentlevel_step = 250
    # Percent-slider ranges (decided tight around realistic SF). Defined here, not retyped
    # in the template (Rule 3): the % sliders share one step. Ranges in PERCENT units.
    slider_pct_step = 0.1
    slider_appr_min, slider_appr_max = 0, 7
    slider_rent_min, slider_rent_max = 1, 6
    slider_market_min, slider_market_max = 4, 10
    # Year-sold slider: 0..longest horizon, step 1 yr; default = the seed sell year.
    slider_sellyear_min = 0
    slider_sellyear_max = max(H)
    slider_sellyear_default = computed["break_even_chart"]["sell_year"]

    # Gain/loss flag for sale-side labels (factual, drives wording not judgment).
    sells_at_loss = sell.capital_gain < 0

    # Everything that is raw HTML gets wrapped in Markup so autoescaping leaves it alone.
    M = Markup
    return {
        "address": p.address,
        "generated": p.as_of_date,
        "home_value": p.home_value,
        "cost_basis": p.cost_basis,
        "primary_invest": PRIMARY_INVEST,
        "marginal_tax": MARGINAL_TAX,
        "cap_gains_rate": CAP_GAINS_RATE,
        "deprec_recapture_rate": DEPREC_RECAPTURE_RATE,
        "fed_recapture_pct": FED_RECAPTURE * 100,
        "niit_pct": NIIT_RATE * 100,
        "ca_top_pct": CA_TOP_RATE * 100,
        "annual_depreciation": m.annual_depreciation,
        "cash_reserve": p.cash_reserve,
        "primary_rent": p.primary_rent,
        "cg_exclusion": CG_EXCLUSION,
        "sale_cost_rate": SALE_COST_RATE,
        "broker_rate": BROKER_RATE,
        "transfer_tax": TRANSFER_TAX,
        "title_escrow": TITLE_ESCROW,
        "sell_soon_max_years": SELL_SOON_MAX_YEARS,
        "longest_horizon": v["longest_horizon"],
        "inflation_pct": v["inflation_rate"] * 100,
        "today_value_pct": v["today_value_fraction"] * 100,
        "worked_horizon": WORKED_EXAMPLE_HORIZON,
        "primary_appreciation": PRIMARY_APPRECIATION,
        "passive_loss_magi_limit": PASSIVE_LOSS_MAGI_LIMIT,
        "sell": sell,
        "we": we,
        "deprec_net": f"{we.deprec_release - we.recapture:+,.0f}",
        "sells_at_loss": sells_at_loss,
        "be_chart_svg": M(be_chart_svg),
        "be_crossover_year": computed["break_even_chart"]["crossover_year"],
        "be_table_seed": M(be_table_seed),
        "cashflow_svg": M(cashflow_svg),
        "cashflow_table_seed": M(cashflow_table_seed),
        "badyear_table_seed": M(badyear_table_seed),
        "sec121_benefit_3yr": sec121_benefit_3yr,
        # Interactive explorer: PARAMS/CHART are pre-serialized JSON (safe to mark Markup
        # for inline <script>); model_js is the inlined engine. Slider defaults/ranges.
        "params_json": M(params_json),
        "chart_json": M(chart_json),
        "model_js": M(model_js),
        "slider_appr_default": slider_appr_default,
        "slider_rent_default": slider_rent_default,
        "slider_market_default": slider_market_default,
        "slider_rentlevel_default": slider_rentlevel_default,
        "slider_rentlevel_min": slider_rentlevel_min,
        "slider_rentlevel_max": slider_rentlevel_max,
        "slider_rentlevel_step": slider_rentlevel_step,
        "slider_pct_step": slider_pct_step,
        "slider_appr_min": slider_appr_min,
        "slider_appr_max": slider_appr_max,
        "slider_rent_min": slider_rent_min,
        "slider_rent_max": slider_rent_max,
        "slider_market_min": slider_market_min,
        "slider_market_max": slider_market_max,
        "slider_sellyear_min": slider_sellyear_min,
        "slider_sellyear_max": slider_sellyear_max,
        "slider_sellyear_default": slider_sellyear_default,
        "assumption_rows": M(assumption_rows),
    }


def main(property_path: str):
    mdl = Model(load_property(property_path))
    os.makedirs(OUTDIR, exist_ok=True)
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html"]),
    )
    ctx = build_context(mdl)
    # Generated output is DATA ONLY (numbers, sensitivities, term/mechanic explanations) —
    # no interpretation/verdict. A separate prompt produces interpretation downstream so
    # it isn't anchored by conclusions baked in here. See CLAUDE.md.
    html = env.get_template("report.html").render(**ctx)
    with open(os.path.join(OUTDIR, "report.html"), "w") as f:
        f.write(html)
    print(f"[wrote {OUTDIR}/report.html for {property_path}]")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python render.py properties/<file>.toml  (the Makefile owns the default)")
    main(sys.argv[1])
