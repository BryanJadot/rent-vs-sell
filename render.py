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

# ── Small HTML row builders (return Markup so Jinja won't re-escape) ──────────


def _nw_row(label_html, values, cls="", bold_last=False):
    cells = ""
    for i, v in enumerate(values):
        inner = f"<b>{v:,.0f}</b>" if (bold_last and i == len(values) - 1) else f"{v:,.0f}"
        cells += f"<td>{inner}</td>"
    return f'<tr class="{cls}"><td>{label_html}</td>{cells}</tr>'


def _break_even_svg(chart: dict) -> str:
    """Inline SVG of HOLD net worth vs. appreciation at the longest horizon, with the
    (flat) SELL line. The two cross at the break-even rate. Drawing only — every number
    comes from compute()'s break_even_chart; this function does no financial math, just
    coordinate mapping. Strictly DATA: two plain lines, a marked crossing, and unlabeled
    reference ticks for the SF history rates. NO shading or labeling of a side as better
    (that would be a verdict — CLAUDE.md rule 2).
    """
    grid = chart["appr_grid"]
    hold = chart["hold"]
    sell = chart["sell"]
    be = chart["break_even"]
    scenarios = chart["scenarios"]

    # Plot box (viewBox units). Margins leave room for axis labels.
    W, Hh = 640, 320
    ml, mr, mt, mb = 64, 16, 16, 40
    x0, x1 = ml, W - mr
    y0, y1 = Hh - mb, mt  # y0 = bottom (pixel), y1 = top

    ax_min, ax_max = grid[0], grid[-1]  # appreciation domain (e.g. 0..0.06)
    y_min = min(min(hold), sell)
    y_max = max(max(hold), sell)
    # pad the value axis a touch so lines don't touch the frame
    pad = (y_max - y_min) * 0.06 or 1.0
    y_min -= pad
    y_max += pad

    def px(a):  # appreciation rate -> x pixel
        return x0 + (a - ax_min) / (ax_max - ax_min) * (x1 - x0)

    def py(v):  # dollars -> y pixel
        return y0 + (v - y_min) / (y_max - y_min) * (y1 - y0)

    hold_pts = " ".join(f"{px(a):.1f},{py(v):.1f}" for a, v in zip(grid, hold))
    sell_y = py(sell)

    parts = [
        f'<svg viewBox="0 0 {W} {Hh}" role="img" '
        'aria-label="Hold net worth vs. appreciation, with the flat sell line; '
        'the lines cross at the break-even appreciation rate." '
        'style="width:100%;height:auto;font:12px system-ui,sans-serif">'
    ]

    # Axes
    parts.append(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y0}" stroke="#bbb"/>')
    parts.append(f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}" stroke="#bbb"/>')

    # Y gridlines + $ labels (a few round ticks)
    yticks = 4
    for i in range(yticks + 1):
        v = y_min + (y_max - y_min) * i / yticks
        yy = py(v)
        parts.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}" stroke="#eee"/>')
        parts.append(
            f'<text x="{x0 - 6}" y="{yy + 4:.1f}" text-anchor="end" fill="#666">'
            f"${v / 1e6:.1f}M</text>"
        )

    # X ticks every 1% across the domain
    a = ax_min
    while a <= ax_max + 1e-9:
        xx = px(a)
        parts.append(
            f'<text x="{xx:.1f}" y="{y0 + 18}" text-anchor="middle" fill="#666">{a * 100:g}%</text>'
        )
        a += 0.01

    # SF history reference ticks (plain vertical dashes, unlabeled as good/bad)
    for rate in scenarios.values():
        if ax_min <= rate <= ax_max:
            xx = px(rate)
            parts.append(
                f'<line x1="{xx:.1f}" y1="{y0}" x2="{xx:.1f}" y2="{y1}" '
                'stroke="#cdd6e5" stroke-dasharray="3 3"/>'
            )
            parts.append(
                f'<text x="{xx:.1f}" y="{y1 + 10:.1f}" text-anchor="middle" '
                f'fill="#90a">{rate * 100:g}%</text>'
            )

    # The two data series
    parts.append(
        f'<line x1="{x0}" y1="{sell_y:.1f}" x2="{x1}" y2="{sell_y:.1f}" '
        'stroke="#2a7" stroke-width="2"/>'
    )
    parts.append(f'<polyline points="{hold_pts}" fill="none" stroke="#36c" stroke-width="2"/>')

    # Crossing point (break-even), if on-domain
    if ax_min <= be <= ax_max:
        bx, by = px(be), sell_y
        parts.append(f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="4" fill="#111"/>')
        parts.append(
            f'<text x="{bx:.1f}" y="{by - 10:.1f}" text-anchor="middle" fill="#111">'
            f"break-even {be * 100:.2f}%</text>"
        )

    # Inline series labels at the right edge
    parts.append(
        f'<text x="{x1 - 4}" y="{py(hold[-1]) - 6:.1f}" text-anchor="end" fill="#36c">Hold</text>'
    )
    parts.append(
        f'<text x="{x1 - 4}" y="{sell_y - 6:.1f}" text-anchor="end" fill="#2a7">Sell now</text>'
    )

    # Axis titles
    parts.append(
        f'<text x="{(x0 + x1) / 2:.0f}" y="{Hh - 4}" text-anchor="middle" fill="#444">'
        "Home appreciation (per year)</text>"
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
            w3 += '<td class="sub">n/a*</td>'
    headline += (
        f"<tr><td>Hold ≤3 yrs then sell "
        f'<span class="sub">(keeps full ${CG_EXCLUSION / 1000:g}k §121)</span></td>{w3}</tr>'
    )
    for rate in INVEST_RATES:
        vals = [m.invest_net_worth(sell.net_proceeds, y, rate) for y in H]
        headline += _nw_row(
            f'<b>Sell now + invest @ {rate * 100:.0f}%</b> <span class="sub">(after-tax)</span>',
            vals,
            cls="sell",
        )

    # Appreciation sensitivity rows (pills/notes derived from assumptions)
    pill_by_key = {"low": "bad", "moderate": "warn", "high": "good"}
    appr_rows = ""
    for key, appr in APPRECIATION.items():
        vals = [m.hold_net_worth(p.primary_rent, y, appr).net_worth for y in H]
        cls = "primary" if abs(appr - PRIMARY_APPRECIATION) < 1e-9 else ""
        lbl = (
            f'{appr * 100:g}%/yr <span class="pill {pill_by_key[key]}">{APPRECIATION_TAGS[key]}</span> '
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
    oop_net = "".join(
        f'<td class="num-bad">−{abs(m.oop_breakdown(r).net):,.0f}</td>' for r in p.realistic_rents
    )
    oop_mo = "".join(
        f'<td class="num-bad">−{abs(m.oop_breakdown(r).net / MONTHS_PER_YEAR):,.0f}</td>'
        for r in p.realistic_rents
    )

    inc_lo = sell.net_proceeds * INVEST_RATES[0]
    inc_hi = sell.net_proceeds * INVEST_RATES[1]

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
            f'Hold <span class="sub">(opp. cost &amp; sell both at {key})</span>',
            [ors["rows"][y][key]["hold"] for y in H],
            cls="primary",
        )
        rate_rows += _nw_row(
            f'Sell + invest @ {key} <span class="sub">(after-tax)</span>',
            [ors["rows"][y][key]["sell"] for y in H],
            cls="sell",
        )

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
        "oop_head": M(oop_head),
        "oop_rows": [M(x) for x in oop_rows],
        "oop_net": M(oop_net),
        "oop_mo": M(oop_mo),
        "risk_rows": M(risk_rows),
        "assumption_rows": M(assumption_rows),
        "inc_lo": inc_lo,
        "inc_hi": inc_hi,
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
