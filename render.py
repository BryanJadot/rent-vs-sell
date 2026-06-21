#!/usr/bin/env python3
"""
render.py — PRESENTATION ONLY for the rent-vs-sell analysis.

Pulls every number from model.compute() and the model's calc functions, builds the
HTML table rows + verdict prose, and renders templates/ into output/. Also writes a
plain-text summary. No financial math lives here — if a number looks wrong, fix
model.py; if a value looks wrong, fix assumptions.py.

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
    AFTERTAX_OPP,
    PRIMARY_INVEST,
    BAD_VACANCY_MONTHS,
    EVICTION_COST,
    MAJOR_REPAIR,
    RISK_VACANCY_PROB,
    RISK_EVICTION_PROB,
    RISK_REPAIR_PROB,
    MOVE_BACK_YEARS,
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
from model import Model, DEFAULT_PROPERTY

OUTDIR = "output"

# ── Small HTML row builders (return Markup so Jinja won't re-escape) ──────────


def _nw_row(label_html, values, cls="", bold_last=False):
    cells = ""
    for i, v in enumerate(values):
        inner = f"<b>{v:,.0f}</b>" if (bold_last and i == len(values) - 1) else f"{v:,.0f}"
        cells += f"<td>{inner}</td>"
    return f'<tr class="{cls}"><td>{label_html}</td>{cells}</tr>'


def _approx(n: float) -> str:
    """Round to nearest $25k to avoid false precision on multi-decade projections."""
    return f"${round(abs(n) / 25_000) * 25:,.0f}k"


def build_context(m: Model) -> dict:
    p = m.p
    sell = m.calc_sell()
    H = HORIZONS
    hz_head = "".join(f"<th>{y}-yr</th>" for y in H)

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
    mb = [
        m.hold_net_worth(p.primary_rent, y, PRIMARY_APPRECIATION, sec121=Sec121.MOVE_BACK).net_worth
        for y in H
    ]
    headline += _nw_row(
        f"Hold, rent ${p.primary_rent / 1000:g}k/mo "
        f'<span class="sub">(move back {MOVE_BACK_YEARS} yrs, partial §121)</span>',
        mb,
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
    rgs = m.compute()["rent_growth_sensitivity"]
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
        '<b>Sell now + invest</b> <span class="sub">(best of 5/7%, after-tax)</span>',
        [rgs["rows"][y]["best_sell"] for y in H],
        cls="sell",
    )

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
    risk = m.compute()["risk"]
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
    low_pct = APPRECIATION["low"] * 100
    mod_pct = APPRECIATION["moderate"] * 100
    high_pct = APPRECIATION["high"] * 100
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
            f"fed {FED_RECAPTURE * 100:g}% + CA ordinary {CA_TOP_RATE * 100:g}%",
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
        (
            "§121 move-back proration",
            "qualified/total yrs",
            f"(res {p.years_owned_as_residence:g}+{MOVE_BACK_YEARS}) / (res {p.years_owned_as_residence:g}+rental+{MOVE_BACK_YEARS}); approximate",
        ),
        ("Cash reserve", f"${p.cash_reserve:,.0f}", "landlord buffer estimate"),
    ]
    assumption_rows = "".join(
        f'<tr><td>{name}</td><td>{val}</td><td class="sub">{src}</td></tr>' for name, val, src in a
    )

    # ── Verdict prose (computed from model facts; never hand-written numbers) ──
    v = m.compute()["verdict"]
    hz = v["longest_horizon"]

    if v["win_cells"] == v["total_cells"]:
        headline_verdict = (
            f"it's an <b>appreciation-dependent bet</b>: holding {v['verb_20']} selling at the central "
            f"{mod_pct:g}% case (on the order of {_approx(v['central_edge'])} at 20 years), but in the "
            f"pessimistic {low_pct:g}% case it {v['verb_low_long']} selling — and the downside is comparable "
            "to or larger than the upside"
        )
    elif v["win_cells"] == 0:
        headline_verdict = (
            "selling comes out ahead at the central case across the realistic rents once "
            "future sale taxes and costs are counted"
        )
    else:
        headline_verdict = (
            f"the two are close at the central case — holding wins in {v['win_cells']} of "
            f"{v['total_cells']} realistic rent/horizon combinations, and the pessimistic "
            f"{low_pct:g}% case it {v['verb_low_long']} selling"
        )

    take = (
        f"At the central {mod_pct:g}% assumption, holding {v['verb_10']} selling at 10 years "
        f"(${v['h10']:,.0f} vs ${v['best_sell_10']:,.0f}) and {v['verb_20']} it at 20 "
        f"(${v['h20']:,.0f} vs ${v['best_sell_20']:,.0f}). The edge is contingent on appreciation: the "
        f"pessimistic {low_pct:g}% case {v['verb_low_long']} selling at {hz} years "
        f"(${v['hold_low_long']:,.0f} vs ${v['sell_long']:,.0f})."
    )

    bet_framing = (
        f"Over {hz} years, holding is a leveraged bet with an <b>asymmetric payoff</b>. "
        f"vs. selling-and-investing (${v['sell_long']:,.0f}): "
        f"upside if SF runs hot ({high_pct:g}%) ≈ <b>{v['upside']:+,.0f}</b>; "
        f"central case ({mod_pct:g}%) ≈ <b>{v['central_edge']:+,.0f}</b>; "
        f"downside if SF lags ({low_pct:g}%) ≈ <b>{v['downside']:+,.0f}</b>. "
        + (
            "The downside loss is larger than the central-case gain — "
            if abs(v["downside"]) > abs(v["central_edge"])
            else ""
        )
        + f"and you carry ~${v['yr1_oop'] / MONTHS_PER_YEAR:,.0f}/mo of negative cash flow throughout to find out which way it breaks."
    )

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
        "aftertax_opp": AFTERTAX_OPP,
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
        "move_back_years": MOVE_BACK_YEARS,
        "sell_soon_max_years": SELL_SOON_MAX_YEARS,
        "appreciation_low": APPRECIATION["low"],
        "longest_horizon": v["longest_horizon"],
        "worked_horizon": WORKED_EXAMPLE_HORIZON,
        "primary_appreciation": PRIMARY_APPRECIATION,
        "passive_loss_magi_limit": PASSIVE_LOSS_MAGI_LIMIT,
        "sell": sell,
        "we": we,
        "deprec_net": f"{we.deprec_release - we.recapture:+,.0f}",
        "hz_head": M(hz_head),
        "headline_rows": M(headline),
        "appr_rows": M(appr_rows),
        "rg_rows": M(rg_rows),
        "rg_low_pct": rg_low_pct,
        "rg_high_pct": rg_high_pct,
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
        "mo_oop": v["mo_oop"],
        "yr1_oop": v["yr1_oop"],
        "yr10_oop": v["yr10_oop"],
        "cum_oop_10": v["cum_oop_10"],
        "reserve_cost_yr": v["reserve_cost_yr"],
        "verb_low_long": v["verb_low_long"],
        "headline_verdict": M(headline_verdict),
        "take": M(take),
        "bet_framing": M(bet_framing),
    }


def write_text_summary(mdl, ctx, path):
    """Plain-text mirror of the headline numbers for results.txt."""
    p = mdl.p
    sell = ctx["sell"]

    def fmt(n):
        return f"${n:>13,.0f}"

    lines = []
    lines.append("=" * 70)
    lines.append(f"  RENT vs. SELL — {p.address}  (generated {p.as_of_date})")
    lines.append("=" * 70)
    lines.append(
        f"  Value {fmt(p.home_value).strip()} | Basis {fmt(p.cost_basis).strip()} | "
        f"Loan {fmt(p.mortgage_bal).strip()} @ {mdl.apr * 100:.3f}%"
    )
    lines.append(
        f"\n  SELL TODAY → net proceeds {fmt(sell.net_proceeds).strip()} "
        f"(costs {fmt(sell.total_costs).strip()}, payoff {fmt(sell.payoff).strip()}); "
        f"cap-gains tax {fmt(sell.tax).strip()} (loss)."
    )
    lines.append(
        f"\n  NET WORTH (rent ${p.primary_rent:,}/mo, {PRIMARY_APPRECIATION * 100:.2f}%, full rental):"
    )
    lines.append("  " + "Option".ljust(26) + "".join(f"{y}yr".rjust(13) for y in HORIZONS))
    lines.append("  " + "─" * (26 + 13 * len(HORIZONS)))
    hold_full = [
        mdl.hold_net_worth(p.primary_rent, y, PRIMARY_APPRECIATION).net_worth for y in HORIZONS
    ]
    lines.append(
        "  " + "Hold (full rental)".ljust(26) + "".join(fmt(x).rjust(13) for x in hold_full)
    )
    for rate in INVEST_RATES:
        row = [mdl.invest_net_worth(sell.net_proceeds, y, rate) for y in HORIZONS]
        lines.append(
            "  "
            + f"Sell + invest @ {rate * 100:.0f}%".ljust(26)
            + "".join(fmt(x).rjust(13) for x in row)
        )
    we = ctx["we"]
    lines.append(
        f"\n  WORKED EXAMPLE — hold {WORKED_EXAMPLE_HORIZON}yr @ ${p.primary_rent:,}, full rental: "
        f"net worth {fmt(we.net_worth).strip()}"
    )
    lines.append(f"\n  Full reports: {OUTDIR}/report.html, {OUTDIR}/interpretation.html")
    text = "\n".join(lines) + "\n"
    with open(path, "w") as f:
        f.write(text)
    return text


def main(property_path: str = DEFAULT_PROPERTY):
    mdl = Model(load_property(property_path))
    os.makedirs(OUTDIR, exist_ok=True)
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html"]),
    )
    ctx = build_context(mdl)
    for name in ("report.html", "interpretation.html"):
        html = env.get_template(name).render(**ctx)
        with open(os.path.join(OUTDIR, name), "w") as f:
            f.write(html)
    write_text_summary(mdl, ctx, os.path.join(OUTDIR, "results.txt"))
    print(
        f"[wrote {OUTDIR}/report.html, {OUTDIR}/interpretation.html, {OUTDIR}/results.txt for {property_path}]"
    )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PROPERTY)
