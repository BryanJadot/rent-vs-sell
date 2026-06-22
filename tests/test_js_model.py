#!/usr/bin/env python3
"""test_js_model.py — the DRIFT GUARD for the JS engine mirror.

static/model.js is a hand-port of model.py's hold/sell math (the one sanctioned
exception to the no-JS rule — see CLAUDE.md). Two copies of financial math is exactly
the silent-drift risk the rest of this project is built to avoid, so this test pins the
JS to the Python: for a grid of (appreciation, rent_growth, market_return, horizon)
points it computes HOLD and SELL net worth in BOTH engines and fails on any disagreement
over $1.

node is REQUIRED — a missing/broken node is a HARD FAILURE, not a skip: the JS engine
must always be verified, so "node isn't here" must turn the suite red rather than quietly
leave the mirror unchecked. (node v22 is present in this environment; `make check` runs it.)
"""

import json
import shutil
import subprocess

import pytest

from assumptions import load_property, Sec121
from model import Model

HAROLD = "properties/harold-ave.toml"
FIXTURE = "properties/test-fixture.toml"

# Sample grid — spans the slider ranges (appr 0–7%, rent 1–6%, market 4–8%) plus the
# base case, across every reported horizon. Deliberately includes edges and the defaults.
APPRS = [0.0, 0.025, 0.0485, 0.06, 0.07]
RENT_GROWTHS = [0.01, 0.03, 0.0485, 0.06]
MARKETS = [0.04, 0.05, 0.07, 0.08, 0.10]  # spans the slider range (market return 4–10%)
HORIZONS = [3, 5, 10, 15, 20, 25, 30]  # spans the 0–30yr time axis, incl. past loan payoff
RENT_LEVELS = [4000, 5000, 6500]  # spans the rent-level slider range ($4k–$6.5k)

# A node driver that loads the engine, reads sample points from stdin, and prints the
# JS HOLD/SELL net worth for each — kept inline so the test is self-contained.
NODE_DRIVER = r"""
const path = require('path');
const engine = require(path.resolve('static/model.js'));
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const P = input.params;
const out = input.points.map((pt) => {
  const hold = engine.holdNetWorth(
    P, pt.rent_level, pt.years, pt.appr, pt.market, 'full_rental', pt.rent_growth
  ).netWorth;
  const sell = engine.investNetWorth(P, engine.calcSell(P).netAfterTax, pt.years, pt.market);
  // Hold-then-invest: hold until sell_year, then invest to the horizon (the live chart/table).
  const hti = engine.holdThenInvestNetWorth(
    P, pt.rent_level, pt.sell_year, pt.years, pt.appr, pt.market, pt.rent_growth
  );
  // Bad-year risk + year-1 out-of-pocket at this rent (the live §2 tables read these).
  const oop = engine.oopBreakdown(P, pt.rent_level).net;
  const risk = engine.riskScenarios(P, pt.rent_level);
  // Negative-principal probe: an underwater hold value compounds as a loss with NO cap-gains
  // tax (the max(0,gain) floor). Pin the JS floor against Python directly.
  const negInvest = engine.investNetWorth(P, -100000, pt.years, pt.market);
  return { hold, sell, hti, oop, worst_total: risk.worst_total, neg_invest: negInvest };
});
process.stdout.write(JSON.stringify(out));
"""


def _points(primary_rent: float):
    """The hold/sell grid runs at the primary rent (keeps the cartesian product bounded);
    a separate sweep varies the rent level so the rent-driven hold/oop/risk paths are
    covered without multiplying the whole grid by every rent."""
    pts = []
    for appr in APPRS:
        for rg in RENT_GROWTHS:
            for mk in MARKETS:
                for yr in HORIZONS:
                    pts.append(
                        {
                            "appr": appr,
                            "rent_growth": rg,
                            "market": mk,
                            "years": yr,
                            "rent_level": primary_rent,
                            "sell_year": 10,  # the seed; a dedicated sweep varies it below
                        }
                    )
    # Rent-level sweep (at the base appr/market/growth, a few horizons) — exercises the
    # rent-driven hold path and the oop/risk mirrors at every slider rent.
    for rl in RENT_LEVELS:
        for yr in (1, 10, 30):
            pts.append(
                {
                    "appr": 0.0485,
                    "rent_growth": 0.03,
                    "market": 0.07,
                    "years": yr,
                    "rent_level": rl,
                    "sell_year": 10,
                }
            )
    # Sell-year sweep — exercises hold-then-invest across S (incl. S=0, S past horizon, and
    # horizons straddling S) at the base case. S ∈ {1,2,3,4} straddles the §121 boundary
    # (SELL_SOON_MAX_YEARS=3, the `<=` vs `>` switch) so the WITHIN_3YR/FULL_RENTAL keying is
    # pinned in both engines, with horizons both at/before and past each S.
    for s in (0, 1, 2, 3, 4, 5, 10, 30):
        for yr in (1, 5, 10, 15, 30):
            pts.append(
                {
                    "appr": 0.0485,
                    "rent_growth": 0.03,
                    "market": 0.07,
                    "years": yr,
                    "rent_level": primary_rent,
                    "sell_year": s,
                }
            )
    return pts


def _run_node(params: dict, points: list[dict]) -> list[dict]:
    node = shutil.which("node")
    # HARD failure if node is absent — the mirror must always be verified (see module doc).
    assert node, "node not found on PATH — the JS drift guard cannot run; install node v22+"
    payload = json.dumps({"params": params, "points": points})
    proc = subprocess.run(
        [node, "-e", NODE_DRIVER],
        input=payload,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"node failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


@pytest.mark.parametrize("prop_path", [HAROLD, FIXTURE])
def test_js_matches_python_within_one_dollar(prop_path):
    """JS HOLD and SELL net worth must match Python within $1 at every sample point.

    Change the Python math and forget static/model.js → this turns red. That is the
    entire point: it makes the second copy of the math safe to keep.
    """
    m = Model(load_property(prop_path))
    params = m.js_params()
    points = _points(m.p.primary_rent)
    js = _run_node(params, points)

    np_ = m.calc_sell().net_after_tax  # SELL invests proceeds net of closing cap-gains tax
    mismatches = []
    for pt, jr in zip(points, js):
        # Python HOLD at the same inputs; rent_growth flows through a second Model so it
        # isn't a global mutation (mirrors compute()'s rent_growth_sensitivity pattern).
        m_rg = Model(m.p, rent_growth=pt["rent_growth"])
        py_hold = m_rg.hold_net_worth(
            pt["rent_level"],
            pt["years"],
            pt["appr"],
            opp_rate=pt["market"],
            sec121=Sec121.FULL_RENTAL,
        ).net_worth
        py_sell = m.invest_net_worth(np_, pt["years"], pt["market"])
        py_hti = m_rg.hold_then_invest_net_worth(
            pt["rent_level"],
            pt["sell_year"],
            pt["years"],
            pt["appr"],
            opp_rate=pt["market"],
        )
        py_oop = m.oop_breakdown(pt["rent_level"]).net
        py_worst = m.risk_scenarios(pt["rent_level"])["worst_total"]
        py_neg = m.invest_net_worth(-100000, pt["years"], pt["market"])

        if abs(py_neg - jr["neg_invest"]) > 1.0:
            mismatches.append(f"NEGINVEST {pt}: py={py_neg:.2f} js={jr['neg_invest']:.2f}")
        if abs(py_hold - jr["hold"]) > 1.0:
            mismatches.append(f"HOLD {pt}: py={py_hold:.2f} js={jr['hold']:.2f}")
        if abs(py_hti - jr["hti"]) > 1.0:
            mismatches.append(f"HTI {pt}: py={py_hti:.2f} js={jr['hti']:.2f}")
        if abs(py_sell - jr["sell"]) > 1.0:
            mismatches.append(f"SELL {pt}: py={py_sell:.2f} js={jr['sell']:.2f}")
        if abs(py_oop - jr["oop"]) > 1.0:
            mismatches.append(f"OOP {pt}: py={py_oop:.2f} js={jr['oop']:.2f}")
        if abs(py_worst - jr["worst_total"]) > 1.0:
            mismatches.append(f"WORST {pt}: py={py_worst:.2f} js={jr['worst_total']:.2f}")

    assert not mismatches, "JS/Python drift >$1:\n" + "\n".join(mismatches[:20])
