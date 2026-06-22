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
    APPRECIATION_NOTES,
    APPRECIATION_TAGS,
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
    """Inline SVG of HOLD and SELL net worth over the holding period (X = years). The two
    curves cross at the crossover year. Drawing only — every number comes from compute()'s
    break_even_chart; this does no financial math, just coordinate mapping. Strictly DATA:
    two plain curves, a marked crossing, and a dashed tick at the mortgage-payoff year
    (which explains the kink in HOLD). NO shading or labeling of a side as better — that
    would be a verdict (CLAUDE.md rule 2). The JS buildSvg mirrors this layout.
    """
    grid = chart["year_grid"]
    hold = chart["hold"]
    sell = chart["sell"]
    crossover = chart["crossover_year"]
    payoff = chart["payoff_year"]

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

    parts = [
        f'<svg viewBox="0 0 {W} {Hh}" role="img" '
        'aria-label="Hold and sell net worth over the holding period in years; '
        'the two curves cross at the crossover year." '
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
        f'<text x="{(x0 + x1) / 2:.0f}" y="{Hh - 4}" text-anchor="middle" fill="#444">'
        "Years held before selling</text>"
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


def build_context(m: Model) -> dict:
    p = m.p
    sell = m.calc_sell()
    H = HORIZONS
    hz_head = "".join(f"<th>{y}-yr</th>" for y in H)
    computed = m.compute()  # one call; index the slices below (compute() is the contract)

    # Headline net-worth rows
    headline = ""
    for rent in p.realistic_rents:
        vals = [m.hold_net_worth(rent, y, PRIMARY_APPRECIATION).net_worth for y in H]
        headline += _nw_row(
            f'<b>Hold, rent ${rent / 1000:g}k/mo</b> <span class="sub">(full rental)</span>',
            vals,
            cls="primary",
            bold_last=True,
        )
    w3 = ""
    for y in H:
        if y <= 3:
            v = m.hold_net_worth(
                p.primary_rent, y, PRIMARY_APPRECIATION, sec121=Sec121.WITHIN_3YR
            ).net_worth
            w3 += f"<td>{v:,.0f}</td>"
        else:
            w3 += '<td class="sub">—</td>'
    headline += (
        f"<tr><td>Sell within 3 yrs "
        f'<span class="sub">(only option that keeps the ${CG_EXCLUSION / 1000:g}k §121 break; '
        f"the dashes mean you'd already have sold)</span></td>{w3}</tr>"
    )
    for rate in INVEST_RATES:
        vals = [m.invest_net_worth(sell.net_after_tax, y, rate) for y in H]
        headline += _nw_row(
            f'<b>Sell now + invest @ {rate * 100:.0f}%</b> <span class="sub">(after-tax)</span>',
            vals,
            cls="sell",
        )

    # Appreciation sensitivity rows. Pills are NEUTRAL (one style for all) — they label
    # which end of the SF history each rate is, not a good/bad valence; a red "bad" /
    # green "good" pill would steer the reader toward a verdict (CLAUDE.md rule 2).
    appr_rows = ""
    for key, appr in APPRECIATION.items():
        vals = [m.hold_net_worth(p.primary_rent, y, appr).net_worth for y in H]
        cls = "primary" if abs(appr - PRIMARY_APPRECIATION) < 1e-9 else ""
        lbl = (
            f'{appr * 100:g}%/yr <span class="pill">{APPRECIATION_TAGS[key]}</span> '
            f'<span class="sub">{APPRECIATION_NOTES[key]}</span>'
        )
        appr_rows += _nw_row(lbl, vals, cls=cls)

    # Rent-growth sensitivity rows (the single biggest swing factor). Data from
    # compute() so render doesn't re-pick the rates.
    rgs = computed["rent_growth_sensitivity"]
    rg_low_pct = rgs["rg_low"] * 100
    rg_high_pct = rgs["rg_high"] * 100
    rg_rows = ""
    rg_rows += _nw_row(
        f'Rent grows {rg_low_pct:g}%/yr <span class="sub">(recent SF ZORI — base)</span>',
        [rgs["rows"][y]["low"] for y in H],
        cls="primary",
    )
    rg_rows += _nw_row(
        f'Rent grows {rg_high_pct:g}%/yr <span class="sub">(tracks home value)</span>',
        [rgs["rows"][y]["high"] for y in H],
    )
    rg_rows += _nw_row(
        '<b>Sell now + invest</b> <span class="sub">(at 7%, the higher opp. rate, after-tax)</span>',
        [rgs["rows"][y]["best_sell"] for y in H],
        cls="sell",
    )

    # Break-even appreciation row: the appreciation rate at which HOLD ties SELL at each
    # horizon (both sides at the primary opp rate). Percentages, not dollars — one row.
    # Data from compute() so render doesn't re-solve. The accompanying note compares it to
    # the SF historical CAGR scenarios; render only formats the numbers it's handed.
    be = computed["break_even"]
    be_cells = "".join(f"<td><b>{be['rows'][y] * 100:.2f}%</b></td>" for y in H)
    be_row = f'<tr class="primary"><td>Appreciation HOLD needs to tie SELL</td>{be_cells}</tr>'
    be_opp_pct = be["opp_rate"] * 100
    be_low_pct = be["scenarios"]["low"] * 100
    be_mod_pct = be["scenarios"]["moderate"] * 100
    be_high_pct = be["scenarios"]["high"] * 100
    be_chart_svg = _break_even_svg(computed["break_even_chart"])
    be_chart_horizon = computed["break_even_chart"]["horizon"]

    # Server-rendered seed for the live horizon table, at the base-case slider defaults
    # (PRIMARY_APPRECIATION / RENT_GROWTH / PRIMARY_INVEST). Identical layout to the JS
    # buildHorizonTable so the static fallback (no-JS / print / first paint) matches what
    # the slider shows. Numbers come from the model; render only arranges them.
    be_tbl_head = "".join(f"<th>{y}-yr</th>" for y in H)
    be_tbl_hold = "".join(
        f"<td>{m.hold_net_worth(p.primary_rent, y, PRIMARY_APPRECIATION, opp_rate=PRIMARY_INVEST).net_worth:,.0f}</td>"
        for y in H
    )
    be_tbl_sell = "".join(
        f"<td>{m.invest_net_worth(sell.net_after_tax, y, PRIMARY_INVEST):,.0f}</td>" for y in H
    )
    be_tbl_gap = ""
    for y in H:
        d = m.hold_net_worth(
            p.primary_rent, y, PRIMARY_APPRECIATION, opp_rate=PRIMARY_INVEST
        ).net_worth - m.invest_net_worth(sell.net_after_tax, y, PRIMARY_INVEST)
        sign = "+" if d >= 0 else "−"
        be_tbl_gap += f"<td>{sign}{abs(d):,.0f}</td>"
    be_table_seed = (
        f"<thead><tr><th>At your assumptions</th>{be_tbl_head}</tr></thead>"
        f'<tbody><tr class="primary"><td>Hold (keep &amp; rent)</td>{be_tbl_hold}</tr>'
        f'<tr class="sell"><td>Sell now + invest</td>{be_tbl_sell}</tr>'
        f'<tr class="total"><td>Hold − Sell</td>{be_tbl_gap}</tr></tbody>'
    )

    # Server-rendered seed for the per-year cash-flow chart (base case). JS swaps it live.
    cashflow_svg = _cashflow_svg(computed["cashflow_chart"])

    # Worked example
    we = m.hold_net_worth(p.primary_rent, WORKED_EXAMPLE_HORIZON, PRIMARY_APPRECIATION)

    # Out-of-pocket cash table. One row per OopBreakdown field (in display order).
    def oop_row(field):
        cells = ""
        for r in p.realistic_rents:
            v = getattr(m.oop_breakdown(r), field)
            cls = "num-bad" if v < 0 else "num-good"
            sign = "−" if v < 0 else "+"
            cells += f'<td class="{cls}">{sign}{abs(v):,.0f}</td>'
        return cells

    oop_head = "".join(f"<th>${r / 1000:g}k/mo</th>" for r in p.realistic_rents)
    oop_rows = [oop_row(f) for f in ("rent_in", "mortgage_out", "opex_out", "tax_back")]

    # Opex broken into its parts (property tax / insurance / repairs / management),
    # each a negative cash row across the rent columns. Components come from calc_rent
    # (Rent.prop_tax, .other_fixed = insurance+repairs, .mgmt, .leasing) — Rule 1, render
    # does no math, just splits the line the model already computed. mgmt+leasing are
    # combined into "Management" since both are management-of-tenant costs.
    def opex_part_row(part_fn):
        cells = ""
        for r in p.realistic_rents:
            v = part_fn(m.calc_rent(r))
            cells += f'<td class="num-bad">−{abs(v):,.0f}</td>'
        return cells

    opex_part_rows = {
        "prop_tax": opex_part_row(lambda rt: rt.prop_tax),
        "insurance": opex_part_row(lambda rt: p.insurance),
        "repairs": opex_part_row(lambda rt: p.repairs),
        "mgmt": opex_part_row(lambda rt: rt.mgmt + rt.leasing),
    }
    oop_net = "".join(
        f'<td class="num-bad">−{abs(m.oop_breakdown(r).net):,.0f}</td>' for r in p.realistic_rents
    )
    oop_mo = "".join(
        f'<td class="num-bad">−{abs(m.oop_breakdown(r).net / MONTHS_PER_YEAR):,.0f}</td>'
        for r in p.realistic_rents
    )

    inc_lo = sell.net_after_tax * INVEST_RATES[0]
    inc_hi = sell.net_after_tax * INVEST_RATES[1]

    # "Other factors" — rent-level range: the longest-horizon hold net worth across a
    # plausible rent band (low = $500 below primary, high = $500 above the upper realistic
    # rent), so §3 can state the magnitude factually. Model owns the math.
    longest_h = max(H)
    rent_lo = p.primary_rent - 500
    rent_hi = max(p.realistic_rents) + 500
    rent_lo_nw = m.hold_net_worth(rent_lo, longest_h, PRIMARY_APPRECIATION).net_worth
    rent_hi_nw = m.hold_net_worth(rent_hi, longest_h, PRIMARY_APPRECIATION).net_worth

    # Risk rows — values come from compute()["risk"] (model owns the math, incl. the
    # net-of-tax major-repair cost; render only arranges).
    risk = computed["risk"]
    base_oop = risk["baseline"]
    scenarios = [
        ("Normal year (baseline)", 0, base_oop),
        (
            f"+ {BAD_VACANCY_MONTHS} months extra vacancy",
            risk["extra_vacancy"],
            base_oop + risk["extra_vacancy"],
        ),
        ("+ Non-paying tenant + eviction", risk["eviction"], base_oop + risk["eviction"]),
        (
            "+ Major repair (roof/foundation), net of tax",
            risk["major_repair"],
            base_oop + risk["major_repair"],
        ),
    ]
    worst_extra = -risk["worst_extra"]
    worst_total = risk["worst_total"]
    risk_rows = ""
    for label, hit, total in scenarios:
        hit_s = "<td>—</td>" if hit == 0 else f'<td class="num-bad">−{abs(hit):,.0f}</td>'
        risk_rows += f'<tr><td>{label}</td>{hit_s}<td class="num-bad">−{abs(total):,.0f}</td></tr>'
    risk_rows += (
        f'<tr class="total"><td>WORST CASE: all three in one year</td>'
        f'<td class="num-bad">−{worst_extra:,.0f}</td>'
        f'<td class="num-bad">−{abs(worst_total):,.0f}</td></tr>'
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
    ]
    assumption_rows = "".join(
        f'<tr><td>{name}</td><td>{val}</td><td class="sub">{src}</td></tr>' for name, val, src in a
    )

    # Neutral cash facts (out-of-pocket figures) — no interpretation; the report states
    # figures and explains terms but draws no conclusion. See CLAUDE.md.
    v = computed["cash_facts"]

    # Opportunity-rate sensitivity rows (hold vs sell at each rate, same rate both sides).
    ors = computed["opp_rate_sensitivity"]
    rate_rows = ""
    for r in ors["rates"]:
        key = f"{int(r * 100)}%"
        rate_rows += _nw_row(
            f'Hold <span class="sub">(both sides earn {key} market return)</span>',
            [ors["rows"][y][key]["hold"] for y in H],
            cls="primary",
        )
        rate_rows += _nw_row(
            f'Sell + invest @ {key} <span class="sub">(after-tax)</span>',
            [ors["rows"][y][key]["sell"] for y in H],
            cls="sell",
        )

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
    slider_appr_default = PRIMARY_APPRECIATION * 100
    slider_rent_default = RENT_GROWTH * 100
    slider_market_default = PRIMARY_INVEST * 100

    # Gain/loss flag for sale-side labels (factual, drives wording not judgment).
    sells_at_loss = sell.capital_gain < 0

    # Everything that is raw HTML gets wrapped in Markup so autoescaping leaves it alone.
    M = Markup
    return {
        "address": p.address,
        "generated": p.as_of_date,
        "home_value": p.home_value,
        "cost_basis": p.cost_basis,
        "mortgage_bal": p.mortgage_bal,
        "apr": m.apr,
        "primary_invest": PRIMARY_INVEST,
        "marginal_tax": MARGINAL_TAX,
        "cap_gains_rate": CAP_GAINS_RATE,
        "deprec_recapture_rate": DEPREC_RECAPTURE_RATE,
        "annual_depreciation": m.annual_depreciation,
        "cash_reserve": p.cash_reserve,
        "rent_growth": RENT_GROWTH,
        "primary_rent": p.primary_rent,
        "cg_exclusion": CG_EXCLUSION,
        "sale_cost_rate": SALE_COST_RATE,
        "broker_rate": BROKER_RATE,
        "transfer_tax": TRANSFER_TAX,
        "title_escrow": TITLE_ESCROW,
        "sell_soon_max_years": SELL_SOON_MAX_YEARS,
        "longest_horizon": v["longest_horizon"],
        "shortest_horizon": v["shortest_horizon"],
        "inflation_pct": v["inflation_rate"] * 100,
        "today_value_pct": v["today_value_fraction"] * 100,
        "worked_horizon": WORKED_EXAMPLE_HORIZON,
        "primary_appreciation": PRIMARY_APPRECIATION,
        "passive_loss_magi_limit": PASSIVE_LOSS_MAGI_LIMIT,
        "sell": sell,
        "we": we,
        "deprec_net": f"{we.deprec_release - we.recapture:+,.0f}",
        "sells_at_loss": sells_at_loss,
        "hz_head": M(hz_head),
        "headline_rows": M(headline),
        "appr_rows": M(appr_rows),
        "rg_rows": M(rg_rows),
        "rg_low_pct": rg_low_pct,
        "rg_high_pct": rg_high_pct,
        "rate_rows": M(rate_rows),
        "be_row": M(be_row),
        "be_opp_pct": be_opp_pct,
        "be_low_pct": be_low_pct,
        "be_mod_pct": be_mod_pct,
        "be_high_pct": be_high_pct,
        "be_chart_svg": M(be_chart_svg),
        "be_chart_horizon": be_chart_horizon,
        "be_table_seed": M(be_table_seed),
        "cashflow_svg": M(cashflow_svg),
        # Interactive explorer: PARAMS/CHART are pre-serialized JSON (safe to mark Markup
        # for inline <script>); model_js is the inlined engine. Slider defaults/ranges.
        "params_json": M(params_json),
        "chart_json": M(chart_json),
        "model_js": M(model_js),
        "slider_appr_default": slider_appr_default,
        "slider_rent_default": slider_rent_default,
        "slider_market_default": slider_market_default,
        "oop_head": M(oop_head),
        "oop_rows": [M(x) for x in oop_rows],
        "opex_part_rows": {k: M(v) for k, v in opex_part_rows.items()},
        "oop_net": M(oop_net),
        "oop_mo": M(oop_mo),
        "risk_rows": M(risk_rows),
        "assumption_rows": M(assumption_rows),
        "inc_lo": inc_lo,
        "inc_hi": inc_hi,
        "invest_lo": INVEST_RATES[0],
        "invest_hi": INVEST_RATES[1],
        "rent_lo": rent_lo,
        "rent_hi": rent_hi,
        "rent_lo_nw": rent_lo_nw,
        "rent_hi_nw": rent_hi_nw,
        "base_oop": base_oop,
        "worst_total": worst_total,
        "reserve_cost_yr": v["reserve_cost_yr"],
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
