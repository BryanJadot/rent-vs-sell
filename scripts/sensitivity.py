#!/usr/bin/env python3
"""Empirical sensitivity analysis of the rent-vs-sell model.

Primary metric: gap = hold_net_worth - sell_net_worth (dollars) at each horizon.
Baseline: primary appreciation, primary rent, primary opp rate (7%), FULL_RENTAL
§121 treatment (the default in hold_net_worth and the realistic long-hold case).

Every shared assumption is imported BY VALUE into model.py's namespace
(`from assumptions import X`), so model functions read them as `model.X`. We perturb
by reassigning the name in the `model` module namespace, run, then restore. Derived
composed rates (CAP_GAINS_RATE, DEPREC_RECAPTURE_RATE, SALE_COST_RATE) are patched at
their final value in `model`. Per-property inputs are perturbed on a copied Property.
"""

import dataclasses
import json

import model as M
from assumptions import load_property, Sec121

prop = load_property("properties/harold-ave.toml")

PRIMARY_APPR = M.PRIMARY_APPRECIATION  # 0.0485
PRIMARY_RENT = prop.primary_rent  # 5000
PRIMARY_OPP = M.PRIMARY_INVEST  # 0.07
HORIZONS = [3, 5, 10, 15, 20]


def gap_and_parts(p=prop, appr=None, rent=None, opp=None, rent_growth=None):
    """Return dict horizon -> (gap, hold_nw, sell_nw) under current module state."""
    appr = PRIMARY_APPR if appr is None else appr
    rent = PRIMARY_RENT if rent is None else rent
    opp = PRIMARY_OPP if opp is None else opp
    # NOTE: Model.__init__ binds rent_growth=RENT_GROWTH as a DEFAULT ARG at def-time,
    # so patching M.RENT_GROWTH does NOT change it — must pass rent_growth explicitly.
    # When unspecified, use the current module-level RENT_GROWTH so the constant-patch
    # path for RENT_GROWTH works correctly.
    rg = M.RENT_GROWTH if rent_growth is None else rent_growth
    m = M.Model(p, rent_growth=rg)
    out = {}
    for y in HORIZONS:
        hold = m.hold_net_worth(rent, y, appr, opp_rate=opp).net_worth
        sell = m.best_sell(y)  # best across INVEST_RATES, the model's sell metric
        out[y] = (hold - sell, hold, sell)
    return out


# Baseline -------------------------------------------------------------------
BASE = gap_and_parts()
print("BASELINE gap (hold - best_sell):")
for y in HORIZONS:
    g, h, s = BASE[y]
    print(f"  {y:2d}yr: gap={g:14,.0f}  hold={h:14,.0f}  sell={s:14,.0f}")


# --- Perturbation machinery --------------------------------------------------
results = []  # each: dict(name, kind, d10, d20, all_h)


def record(name, kind, perturbed, detail=""):
    d = {"name": name, "kind": kind, "detail": detail}
    for y in HORIZONS:
        d[f"g{y}"] = perturbed[y][0] - BASE[y][0]
        d[f"absg{y}"] = perturbed[y][0]
        d[f"hold{y}"] = perturbed[y][1]
        d[f"sell{y}"] = perturbed[y][2]
    results.append(d)
    return d


# --- Shared constants: patch in model namespace ------------------------------
# (name_in_model, baseline_value, is_rate?)  rates get ±1pp; all get ±10%.
SHARED_RATES = [
    ("VACANCY_RATE", M.VACANCY_RATE),
    ("MGMT_RATE", M.MGMT_RATE),
    ("RENT_GROWTH", M.RENT_GROWTH),
    ("PROPERTY_TAX_GROWTH", M.PROPERTY_TAX_GROWTH),
    ("EXPENSE_GROWTH", M.EXPENSE_GROWTH),
    ("MARGINAL_TAX", M.MARGINAL_TAX),
    ("NIIT_RATE", M.NIIT_RATE),
    ("CAP_GAINS_RATE", M.CAP_GAINS_RATE),
    ("DEPREC_RECAPTURE_RATE", M.DEPREC_RECAPTURE_RATE),
    ("SALE_COST_RATE", M.SALE_COST_RATE),
    ("RESERVE_RATE", M.RESERVE_RATE),
    ("RISK_VACANCY_PROB", M.RISK_VACANCY_PROB),
    ("RISK_EVICTION_PROB", M.RISK_EVICTION_PROB),
    ("RISK_REPAIR_PROB", M.RISK_REPAIR_PROB),
]
SHARED_DOLLARS = [
    ("CG_EXCLUSION", M.CG_EXCLUSION),
    ("EVICTION_COST", M.EVICTION_COST),
    ("MAJOR_REPAIR", M.MAJOR_REPAIR),
    ("BAD_VACANCY_MONTHS", M.BAD_VACANCY_MONTHS),
    ("DEPREC_YEARS", M.DEPREC_YEARS),
]


def patch_shared(name, value, **kw):
    old = getattr(M, name)
    setattr(M, name, value)
    try:
        return gap_and_parts(**kw)
    finally:
        setattr(M, name, old)


for name, base in SHARED_RATES:
    # ±1 percentage point
    up = patch_shared(name, base + 0.01)
    dn = patch_shared(name, base - 0.01)
    # symmetric magnitude: average of |Δ| up and down, but keep signed via up-direction
    record(name, "+1pp", up, detail=f"{base:.4f}->{base + 0.01:.4f}")
    record(name, "-1pp", dn, detail=f"{base:.4f}->{base - 0.01:.4f}")
    # ±10% relative
    up10 = patch_shared(name, base * 1.10)
    dn10 = patch_shared(name, base * 0.90)
    record(name, "+10%", up10, detail=f"{base:.4f}->{base * 1.1:.4f}")
    record(name, "-10%", dn10, detail=f"{base:.4f}->{base * 0.9:.4f}")

for name, base in SHARED_DOLLARS:
    up10 = patch_shared(name, base * 1.10)
    dn10 = patch_shared(name, base * 0.90)
    record(name, "+10%", up10, detail=f"{base}->{base * 1.1:g}")
    record(name, "-10%", dn10, detail=f"{base}->{base * 0.9:g}")


# --- Driver inputs passed directly to gap_and_parts --------------------------
# APPRECIATION (primary appreciation): ±1pp and ±10%
record(
    "APPRECIATION",
    "+1pp",
    gap_and_parts(appr=PRIMARY_APPR + 0.01),
    f"{PRIMARY_APPR:.4f}->{PRIMARY_APPR + 0.01:.4f}",
)
record(
    "APPRECIATION",
    "-1pp",
    gap_and_parts(appr=PRIMARY_APPR - 0.01),
    f"{PRIMARY_APPR:.4f}->{PRIMARY_APPR - 0.01:.4f}",
)
record("APPRECIATION", "+10%", gap_and_parts(appr=PRIMARY_APPR * 1.1), "")
record("APPRECIATION", "-10%", gap_and_parts(appr=PRIMARY_APPR * 0.9), "")

# OPP_RATE (compounding rate on BOTH sides): ±1pp and ±10%
record(
    "OPP_RATE",
    "+1pp",
    gap_and_parts(opp=PRIMARY_OPP + 0.01),
    f"{PRIMARY_OPP:.4f}->{PRIMARY_OPP + 0.01:.4f}",
)
record(
    "OPP_RATE",
    "-1pp",
    gap_and_parts(opp=PRIMARY_OPP - 0.01),
    f"{PRIMARY_OPP:.4f}->{PRIMARY_OPP - 0.01:.4f}",
)
record("OPP_RATE", "+10%", gap_and_parts(opp=PRIMARY_OPP * 1.1), "")
record("OPP_RATE", "-10%", gap_and_parts(opp=PRIMARY_OPP * 0.9), "")

# RENT_GROWTH via Model arg (same as patching the constant, but explicit) -- already
# covered by SHARED_RATES RENT_GROWTH. Skip duplicate.

# MONTHLY RENT level: ±10% (a "rate" analog isn't natural; use $ levels) and ±1pp N/A
record(
    "RENT_LEVEL",
    "+10%",
    gap_and_parts(rent=PRIMARY_RENT * 1.1),
    f"{PRIMARY_RENT}->{PRIMARY_RENT * 1.1:g}",
)
record(
    "RENT_LEVEL",
    "-10%",
    gap_and_parts(rent=PRIMARY_RENT * 0.9),
    f"{PRIMARY_RENT}->{PRIMARY_RENT * 0.9:g}",
)


# --- Per-property inputs: perturb on a copied Property ------------------------
def with_field(field, value):
    p2 = dataclasses.replace(prop, **{field: value})
    return p2


PROP_FIELDS = [
    "home_value",
    "cost_basis",
    "building_basis",
    "mortgage_bal",
    "monthly_pi",
    "property_tax",
    "insurance",
    "repairs",
    "cash_reserve",
]
for f in PROP_FIELDS:
    base = getattr(prop, f)
    up = gap_and_parts(p=with_field(f, base * 1.10))
    dn = gap_and_parts(p=with_field(f, base * 0.90))
    record(f, "+10%", up, f"{base:g}->{base * 1.1:g}")
    record(f, "-10%", dn, f"{base:g}->{base * 0.9:g}")


# --- Plausible-range swings --------------------------------------------------
ranges = {}
# appreciation 2.5% - 6%
ga_lo = gap_and_parts(appr=0.025)
ga_hi = gap_and_parts(appr=0.06)
ranges["APPRECIATION 2.5%-6%"] = (ga_lo, ga_hi)
# rent 4500-6000
gr_lo = gap_and_parts(rent=4500)
gr_hi = gap_and_parts(rent=6000)
ranges["RENT $4.5k-$6k"] = (gr_lo, gr_hi)
# opp rate 5%-7%
go_lo = gap_and_parts(opp=0.05)
go_hi = gap_and_parts(opp=0.07)
ranges["OPP_RATE 5%-7%"] = (go_lo, go_hi)


# rent growth 2% - 4.85% (decoupled low to recoupled-with-appr)
def rg_run(v):
    return gap_and_parts(rent_growth=v)


grg_lo = rg_run(0.02)
grg_hi = rg_run(0.0485)
ranges["RENT_GROWTH 2%-4.85%"] = (grg_lo, grg_hi)


# §121 treatment: FULL_RENTAL (baseline) vs WITHIN_3YR (only differs <=3yr)
def gap_sec121(sec):
    m = M.Model(prop)
    out = {}
    for y in HORIZONS:
        hold = m.hold_net_worth(
            PRIMARY_RENT, y, PRIMARY_APPR, opp_rate=PRIMARY_OPP, sec121=sec
        ).net_worth
        sell = m.best_sell(y)
        out[y] = (hold - sell, hold, sell)
    return out


g_full = gap_sec121(Sec121.FULL_RENTAL)
g_w3 = gap_sec121(Sec121.WITHIN_3YR)
ranges["SEC121 full_rental->within_3yr"] = (g_full, g_w3)


# --- Output ------------------------------------------------------------------
def fmt(x):
    return f"{x:>13,.0f}"


print("\n\n=== Δgap vs baseline, sorted by |Δgap@20yr| ===")
for kind_filter in ["+1pp", "+10%"]:
    print(f"\n--- perturbation kind: {kind_filter} ---")
    rows = [r for r in results if r["kind"] == kind_filter]
    rows.sort(key=lambda r: abs(r["g20"]), reverse=True)
    print(f"{'input':22} {'Δgap10':>13} {'Δgap20':>13}  {'Δhold20':>13} {'Δsell20':>13}")
    for r in rows:
        dh20 = r["hold20"] - BASE[20][1]
        ds20 = r["sell20"] - BASE[20][2]
        print(f"{r['name']:22} {fmt(r['g10'])} {fmt(r['g20'])}  {fmt(dh20)} {fmt(ds20)}")

print("\n\n=== PLAUSIBLE-RANGE swings (gap@lo, gap@hi, swing@10, swing@20) ===")
range_rows = []
for label, (lo, hi) in ranges.items():
    s10 = hi[10][0] - lo[10][0]
    s20 = hi[20][0] - lo[20][0]
    range_rows.append((label, lo, hi, s10, s20))
range_rows.sort(key=lambda x: abs(x[4]), reverse=True)
for label, lo, hi, s10, s20 in range_rows:
    print(
        f"{label:34} gap10:{fmt(lo[10][0])}->{fmt(hi[10][0])} (Δ{fmt(s10)})  "
        f"gap20:{fmt(lo[20][0])}->{fmt(hi[20][0])} (Δ{fmt(s20)})"
    )

# Dump machine-readable for the markdown writer
with open("output/sensitivity_raw.json", "w") as fh:
    json.dump(
        {
            "baseline": {
                str(y): {"gap": BASE[y][0], "hold": BASE[y][1], "sell": BASE[y][2]}
                for y in HORIZONS
            },
            "results": results,
            "ranges": {
                label: {
                    "lo": {str(y): lo[y][0] for y in HORIZONS},
                    "hi": {str(y): hi[y][0] for y in HORIZONS},
                }
                for label, (lo, hi) in ranges.items()
            },
        },
        fh,
        indent=2,
    )
print("\n[wrote output/sensitivity_raw.json]")
