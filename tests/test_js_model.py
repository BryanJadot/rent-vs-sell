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
    P, P.primary_rent, pt.years, pt.appr, pt.market, 'full_rental', pt.rent_growth
  ).netWorth;
  const sell = engine.investNetWorth(P, engine.calcSell(P).netProceeds, pt.years, pt.market);
  return { hold, sell };
});
process.stdout.write(JSON.stringify(out));
"""


def _points():
    pts = []
    for appr in APPRS:
        for rg in RENT_GROWTHS:
            for mk in MARKETS:
                for yr in HORIZONS:
                    pts.append({"appr": appr, "rent_growth": rg, "market": mk, "years": yr})
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
    points = _points()
    js = _run_node(params, points)

    np_ = m.calc_sell().net_proceeds
    mismatches = []
    for pt, jr in zip(points, js):
        # Python HOLD at the same inputs; rent_growth flows through a second Model so it
        # isn't a global mutation (mirrors compute()'s rent_growth_sensitivity pattern).
        m_rg = Model(m.p, rent_growth=pt["rent_growth"])
        py_hold = m_rg.hold_net_worth(
            m.p.primary_rent,
            pt["years"],
            pt["appr"],
            opp_rate=pt["market"],
            sec121=Sec121.FULL_RENTAL,
        ).net_worth
        py_sell = m.invest_net_worth(np_, pt["years"], pt["market"])

        if abs(py_hold - jr["hold"]) > 1.0:
            mismatches.append(f"HOLD {pt}: py={py_hold:.2f} js={jr['hold']:.2f}")
        if abs(py_sell - jr["sell"]) > 1.0:
            mismatches.append(f"SELL {pt}: py={py_sell:.2f} js={jr['sell']:.2f}")

    assert not mismatches, "JS/Python drift >$1:\n" + "\n".join(mismatches[:20])
