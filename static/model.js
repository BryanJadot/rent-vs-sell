/* static/model.js — JS MIRROR of model.py's hold-vs-sell engine.
 *
 * This is the ONE sanctioned exception to the project's no-JS-math rule (CLAUDE.md):
 * the interactive break-even explorer needs continuous sliders, so the HOLD/SELL math
 * is ported here to run client-side. It is NOT a second source of truth — it is a
 * deliberate mirror of model.py, pinned to the Python within $1 by tests/test_js_model.py
 * (run under node in `make check`). If you change the financial math in model.py, you
 * MUST update this file and keep that test green.
 *
 * Every constant + per-property number is read from PARAMS (injected by render from
 * Model.js_params()) — nothing Python owns is retyped here (CLAUDE.md rule 3). When run
 * in the browser, render sets `globalThis.PARAMS`; when run under node for the drift
 * test, the harness assigns PARAMS before calling the engine.
 *
 * Sign/unit conventions match model.py exactly: outflows negative; rates in [0,1];
 * dollars nominal. Comments here are intentionally terse and point back to the named
 * model.py function — the authoritative "why" lives there (rule 6).
 */

// ── Engine (pure functions; mirror of model.py) ──────────────────────────────
// All take an explicit `P` params object so the test harness can drive them without
// any global. In the browser these are called via the thin wrappers at the bottom
// that pass the injected PARAMS.

function deriveMonthlyRate(P) {
  // model.py uses _derive_monthly_rate at load time; render injects the already-solved
  // monthly_rate, so we just read it (no need to re-bisect client-side).
  return P.monthly_rate;
}

function annualDepreciation(P) {
  // building_basis / DEPREC_YEARS (straight-line, building only)
  return P.building_basis / P.deprec_years;
}

function annualDeprecShield(P) {
  // 0 when passive losses are suspended (the modeled case); else deprec × marginal rate.
  return P.passive_loss_usable_yearly ? annualDepreciation(P) * P.marginal_tax : 0.0;
}

function netMajorRepair(P) {
  // Capital improvement → net economic cost ≈ outlay × (1 − cap-gains rate). See model.py.
  return P.major_repair * (1 - P.cap_gains_rate);
}

function excessVacancyMonths(P) {
  return P.bad_vacancy_months - P.months_per_year * P.vacancy_rate;
}

function expectedRiskDrag(P) {
  // prob-weighted vacancy(excess)/eviction/repair drag (Model.__init__)
  return (
    P.risk_vacancy_prob * (excessVacancyMonths(P) * P.primary_rent) +
    P.risk_eviction_prob * P.eviction_cost +
    P.risk_repair_prob * netMajorRepair(P)
  );
}

function amortizationSchedule(P, years) {
  // Year-by-year [interestPaid, endingBalance] — mirror of Model.amortization_schedule.
  let bal = P.mortgage_bal;
  let monthsLeft = P.payments_left;
  const r = deriveMonthlyRate(P);
  const out = [];
  for (let y = 0; y < years; y++) {
    let interestYr = 0.0;
    for (let mo = 0; mo < P.months_per_year; mo++) {
      if (monthsLeft <= 0 || bal <= 0) break;
      const interest = bal * r;
      interestYr += interest;
      bal -= P.monthly_pi - interest;
      monthsLeft -= 1;
    }
    out.push([interestYr, bal]);
  }
  return out;
}

function principalPaidOver(P, years) {
  // [principalPaid, remainingBalance] after `years` (Model.principal_paid_over)
  const sched = amortizationSchedule(P, years);
  const remaining = sched.length ? sched[sched.length - 1][1] : P.mortgage_bal;
  return [P.mortgage_bal - remaining, remaining];
}

function calcRent(P, monthlyRent, yearIndex) {
  // Mirror of Model.calc_rent. Returns the fields the engine consumes.
  const gross = monthlyRent * P.months_per_year;
  const vacancy = gross * P.vacancy_rate;
  const egi = gross - vacancy;
  const mgmt = egi * P.mgmt_rate;
  const leasing = (monthlyRent * P.leasing_fee_months) / P.tenancy_years;
  const propTax = P.property_tax * Math.pow(1 + P.property_tax_growth, yearIndex);
  const otherFixed = (P.insurance + P.repairs) * Math.pow(1 + P.expense_growth, yearIndex);
  const fixed = propTax + otherFixed;
  const op = fixed + mgmt + leasing;
  const noi = egi - op;
  const annualPi = P.monthly_pi * P.months_per_year;
  const cashFlow = noi - annualPi;
  return { gross, vacancy, egi, mgmt, leasing, propTax, otherFixed, fixed, op, noi, annualPi, cashFlow };
}

function yearCashFlow(P, monthlyRent, yearIndex, rentGrowth) {
  // Mirror of Model._year_cash_flow (economic cash; rentGrowth is the instance attr).
  const rentThisYr = monthlyRent * Math.pow(1 + rentGrowth, yearIndex);
  return (
    calcRent(P, rentThisYr, yearIndex).cashFlow +
    annualDeprecShield(P) -
    expectedRiskDrag(P)
  );
}

function taxableRentalIncome(P, monthlyRent, yearIndex, interestYr, rentGrowth) {
  // Mirror of Model._taxable_rental_income (only interest deductible; deprec stops at 27.5y).
  const rentThisYr = monthlyRent * Math.pow(1 + rentGrowth, yearIndex);
  const r = calcRent(P, rentThisYr, yearIndex);
  const deprec = yearIndex < P.deprec_years ? annualDepreciation(P) : 0.0;
  return r.egi - r.op - interestYr - deprec;
}

function profitYearTaxes(P, monthlyRent, years, rentGrowth) {
  // Mirror of Model._profit_year_taxes (§469 pool absorbs profit; excess taxed at marginal+NIIT).
  const schedule = amortizationSchedule(P, years);
  let pool = 0.0;
  const taxes = [];
  for (let yr = 0; yr < years; yr++) {
    const ti = taxableRentalIncome(P, monthlyRent, yr, schedule[yr][0], rentGrowth);
    if (ti < 0) {
      if (!P.passive_loss_usable_yearly) pool += -ti;
      taxes.push(0.0);
    } else {
      let taxable = ti;
      if (!P.passive_loss_usable_yearly) {
        const absorbed = Math.min(pool, ti);
        pool -= absorbed;
        taxable = ti - absorbed;
      }
      taxes.push(taxable * (P.marginal_tax + P.niit_rate));
    }
  }
  return taxes;
}

function compoundedCashFlow(P, monthlyRent, years, pretaxRate, rentGrowth) {
  // Mirror of Model.compounded_cash_flow: grow pre-tax, tax the gain once at liquidation.
  const profitTaxes = profitYearTaxes(P, monthlyRent, years, rentGrowth);
  let fv = 0.0;
  for (let yr = 0; yr < years; yr++) {
    const cf = yearCashFlow(P, monthlyRent, yr, rentGrowth) - profitTaxes[yr];
    const growth = Math.pow(1 + pretaxRate, years - yr - 1);
    fv += cf * (1 + (growth - 1) * (1 - P.cap_gains_rate));
  }
  return fv;
}

function suspendedOperatingLosses(P, monthlyRent, years, rentGrowth) {
  // Mirror of Model.suspended_operating_losses (§469 running pool, floored at 0).
  if (P.passive_loss_usable_yearly) return 0.0;
  let pool = 0.0;
  const schedule = amortizationSchedule(P, years);
  for (let yr = 0; yr < years; yr++) {
    const ti = taxableRentalIncome(P, monthlyRent, yr, schedule[yr][0], rentGrowth);
    pool = Math.max(0.0, pool - ti);
  }
  return pool;
}

function excludedGain(P, treatment, appreciationGain, years) {
  // Mirror of model.excluded_gain. treatment: "full_rental" | "within_3yr".
  if (treatment === "within_3yr" && years <= P.sell_soon_max_years) {
    return Math.min(P.cg_exclusion, appreciationGain);
  }
  return 0.0;
}

function taxAtSale(P, accumulatedDeprec, suspendedLoss, realizedAmount, costBasis, treatment, years) {
  // Mirror of model.tax_at_sale (§1250 recapture cap + §121 exclusion).
  const adjustedBasis = costBasis - accumulatedDeprec;
  const recognizedGain = realizedAmount - adjustedBasis;
  const recaptureBase = Math.max(0.0, Math.min(accumulatedDeprec, recognizedGain));
  const recapture = recaptureBase * P.deprec_recapture_rate;
  const deprecRelease = suspendedLoss * P.marginal_tax;
  const appreciationGain = Math.max(0.0, realizedAmount - costBasis);
  const excluded = excludedGain(P, treatment, appreciationGain, years);
  const taxableGain = Math.max(0.0, appreciationGain - excluded);
  const capGainsTax = taxableGain * P.cap_gains_rate;
  return { recapture, deprecRelease, capGainsTax, excludedGain: excluded, appreciationGain };
}

function calcSell(P) {
  // Mirror of Model.calc_sell → net proceeds for the sell-today side.
  const broker = P.home_value * P.broker_rate;
  const transfer = P.home_value * P.transfer_tax;
  const title = P.home_value * P.title_escrow;
  const total = broker + transfer + title;
  const net = P.home_value - total - P.mortgage_bal;
  return { netProceeds: net };
}

function holdNetWorth(P, monthlyRent, years, appr, oppRate, sec121, rentGrowth) {
  // Mirror of Model.hold_net_worth. sec121: "full_rental" | "within_3yr".
  oppRate = oppRate === undefined ? P.primary_invest : oppRate;
  sec121 = sec121 || "full_rental";
  rentGrowth = rentGrowth === undefined ? P.rent_growth : rentGrowth;

  const futureValue = P.home_value * Math.pow(1 + appr, years);
  const [, remaining] = principalPaidOver(P, years);
  const saleCosts = futureValue * P.sale_cost_rate;
  const grossEquity = futureValue - remaining - saleCosts;

  const cashFv = compoundedCashFlow(P, monthlyRent, years, oppRate, rentGrowth);

  const accumulatedDeprec = annualDepreciation(P) * Math.min(years, P.deprec_years);
  const suspendedLoss = suspendedOperatingLosses(P, monthlyRent, years, rentGrowth);
  const realizedAmount = futureValue - saleCosts;
  const st = taxAtSale(P, accumulatedDeprec, suspendedLoss, realizedAmount, P.cost_basis, sec121, years);

  const oppGrowth = Math.pow(1 + oppRate, years);
  const bondGrowth = Math.pow(1 + P.reserve_rate, years);
  const reserveOppCost = P.cash_reserve * (oppGrowth - bondGrowth) * (1 - P.cap_gains_rate);

  const netWorth =
    grossEquity + cashFv + st.deprecRelease - st.recapture - st.capGainsTax - reserveOppCost;
  return { futureValue, remaining, saleCosts, grossEquity, cashFv, ...st, reserveOppCost, netWorth };
}

function investNetWorth(P, netProceeds, years, rate) {
  // Mirror of Model.invest_net_worth (gain taxed once at liquidation).
  const ending = netProceeds * Math.pow(1 + rate, years);
  const gain = ending - netProceeds;
  return ending - gain * P.cap_gains_rate;
}

function bestSell(P, years) {
  // Mirror of Model.best_sell — best of the invest-rate scenarios.
  const np = calcSell(P).netProceeds;
  return Math.max(...P.invest_rates.map((r) => investNetWorth(P, np, years, r)));
}

function breakEvenAppreciation(P, years, oppRate, rentGrowth) {
  // Mirror of Model.break_even_appreciation — bisect appr s.t. HOLD ties SELL, both at oppRate.
  oppRate = oppRate === undefined ? P.primary_invest : oppRate;
  rentGrowth = rentGrowth === undefined ? P.rent_growth : rentGrowth;
  const target = investNetWorth(P, calcSell(P).netProceeds, years, oppRate);
  let lo = -0.1;
  let hi = 0.25;
  for (let i = 0; i < 100; i++) {
    const mid = (lo + hi) / 2;
    const nw = holdNetWorth(P, P.primary_rent, years, mid, oppRate, "full_rental", rentGrowth).netWorth;
    if (nw < target) lo = mid;
    else hi = mid;
  }
  return (lo + hi) / 2;
}

// Export for node (drift test). In the browser there is no module, so guard it.
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    annualDepreciation,
    expectedRiskDrag,
    amortizationSchedule,
    calcRent,
    compoundedCashFlow,
    suspendedOperatingLosses,
    taxAtSale,
    calcSell,
    holdNetWorth,
    investNetWorth,
    bestSell,
    breakEvenAppreciation,
  };
}

// ── Browser layer: chart redraw + slider wiring ──────────────────────────────
// Everything below only runs in a browser (guarded on `document`). render injects
// globalThis.PARAMS and the chart geometry constants (CHART) before this file.

if (typeof document !== "undefined") {
  const P = globalThis.PARAMS;
  const C = globalThis.CHART; // {W,Hh,ml,mr,mt,mb,apprGrid,horizon,scenarios,step}

  const fmtM = (v) => {
    const m = v / 1e6;
    return m < 0 ? `−$${Math.abs(m).toFixed(1)}M` : `$${m.toFixed(1)}M`;
  };
  const fmtDollars = (v) =>
    (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString("en-US");

  // Mirror of render._break_even_svg coordinate mapping. Pure string-building; no math
  // that affects the model — the model numbers come from the engine above.
  function buildSvg(appr, rentGrowth, marketRate) {
    const grid = C.apprGrid;
    const years = C.horizon;
    const hold = grid.map(
      (a) => holdNetWorth(P, P.primary_rent, years, a, marketRate, "full_rental", rentGrowth).netWorth
    );
    // SELL line at the chosen market return — the SAME basis breakEvenAppreciation solves
    // against, so the green line and the marked crossing are guaranteed consistent.
    const sell = investNetWorth(P, calcSell(P).netProceeds, years, marketRate);
    const be = breakEvenAppreciation(P, years, marketRate, rentGrowth);

    const W = C.W, Hh = C.Hh;
    const ml = C.ml, mr = C.mr, mt = C.mt, mb = C.mb;
    const x0 = ml, x1 = W - mr;
    const y0 = Hh - mb, y1 = mt;
    const axMin = grid[0], axMax = grid[grid.length - 1];

    const rawLo = Math.min(Math.min(...hold), sell);
    const rawHi = Math.max(Math.max(...hold), sell);
    const step = C.step;
    let yMin = Math.floor(rawLo / step) * step;
    let yMax = Math.ceil(rawHi / step) * step;
    if (yMax === yMin) yMax = yMin + step;

    const px = (a) => x0 + ((a - axMin) / (axMax - axMin)) * (x1 - x0);
    const py = (v) => y0 + ((v - yMin) / (yMax - yMin)) * (y1 - y0);

    const holdPts = grid.map((a, i) => `${px(a).toFixed(1)},${py(hold[i]).toFixed(1)}`).join(" ");
    const sellY = py(sell);
    const parts = [];

    parts.push(
      `<svg viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Hold net worth vs. appreciation, ` +
        `with the flat sell line; the lines cross at the break-even appreciation rate." ` +
        `style="width:100%;height:auto;font:12px system-ui,sans-serif">`
    );
    parts.push(`<line x1="${x0}" y1="${y0}" x2="${x1}" y2="${y0}" stroke="#bbb"/>`);
    parts.push(`<line x1="${x0}" y1="${y0}" x2="${x0}" y2="${y1}" stroke="#bbb"/>`);

    const nSteps = Math.round((yMax - yMin) / step);
    for (let i = 0; i <= nSteps; i++) {
      const v = yMin + i * step;
      const yy = py(v);
      parts.push(`<line x1="${x0}" y1="${yy.toFixed(1)}" x2="${x1}" y2="${yy.toFixed(1)}" stroke="#eee"/>`);
      parts.push(
        `<text x="${x0 - 6}" y="${(yy + 4).toFixed(1)}" text-anchor="end" fill="#666">${fmtM(v)}</text>`
      );
    }

    for (let a = axMin; a <= axMax + 1e-9; a += 0.01) {
      const xx = px(a);
      parts.push(
        `<text x="${xx.toFixed(1)}" y="${y0 + 18}" text-anchor="middle" fill="#666">${+(a * 100).toFixed(2)}%</text>`
      );
    }

    for (const rate of Object.values(C.scenarios)) {
      if (axMin <= rate && rate <= axMax) {
        const xx = px(rate);
        parts.push(
          `<line x1="${xx.toFixed(1)}" y1="${y0}" x2="${xx.toFixed(1)}" y2="${y1}" stroke="#cdd6e5" stroke-dasharray="3 3"/>`
        );
        const anchor = xx > x1 - 24 ? "end" : "middle";
        const lx = anchor === "end" ? x1 : xx;
        parts.push(
          `<text x="${lx.toFixed(1)}" y="${(y1 - 10).toFixed(1)}" text-anchor="${anchor}" fill="#90a">${+(rate * 100).toFixed(2)}%</text>`
        );
      }
    }

    parts.push(`<line x1="${x0}" y1="${sellY.toFixed(1)}" x2="${x1}" y2="${sellY.toFixed(1)}" stroke="#2a7" stroke-width="2"/>`);
    parts.push(`<polyline points="${holdPts}" fill="none" stroke="#36c" stroke-width="2"/>`);

    if (axMin <= be && be <= axMax) {
      const bx = px(be), by = sellY;
      parts.push(`<circle cx="${bx.toFixed(1)}" cy="${by.toFixed(1)}" r="4" fill="#111"/>`);
      parts.push(
        `<text x="${bx.toFixed(1)}" y="${(by - 10).toFixed(1)}" text-anchor="middle" fill="#111">break-even ${(be * 100).toFixed(2)}%</text>`
      );
    }

    // Marker for the CURRENT appreciation slider value on the Hold curve.
    if (axMin <= appr && appr <= axMax) {
      const ax = px(appr);
      const ay = py(holdNetWorth(P, P.primary_rent, years, appr, marketRate, "full_rental", rentGrowth).netWorth);
      parts.push(`<circle cx="${ax.toFixed(1)}" cy="${ay.toFixed(1)}" r="4" fill="#36c"/>`);
      parts.push(`<line x1="${ax.toFixed(1)}" y1="${y0}" x2="${ax.toFixed(1)}" y2="${ay.toFixed(1)}" stroke="#36c" stroke-dasharray="2 2"/>`);
    }

    parts.push(`<text x="${(x0 + 6).toFixed(1)}" y="${(py(hold[0]) - 8).toFixed(1)}" text-anchor="start" fill="#36c">Hold</text>`);
    parts.push(`<text x="${(x0 + 6).toFixed(1)}" y="${(sellY - 8).toFixed(1)}" text-anchor="start" fill="#2a7">Sell now</text>`);
    parts.push(
      `<text x="${((x0 + x1) / 2).toFixed(0)}" y="${Hh - 4}" text-anchor="middle" fill="#444">Home appreciation (per year)</text>`
    );
    parts.push("</svg>");
    return parts.join("");
  }

  // Neutral readout: figures only — gap at the longest horizon + crossover year.
  // No "you should"/"better"/"win" (CLAUDE.md rule 2).
  function buildReadout(appr, rentGrowth, marketRate) {
    const horizons = P.horizons;
    const hz = Math.max(...horizons);
    const hold = holdNetWorth(P, P.primary_rent, hz, appr, marketRate, "full_rental", rentGrowth).netWorth;
    const sell = investNetWorth(P, calcSell(P).netProceeds, hz, marketRate);
    const gap = Math.abs(hold - sell);

    // Crossover horizon: the first horizon where the sign of (hold − sell) differs from
    // the shortest horizon's sign. Stated as a neutral fact, not a verdict.
    const diffs = horizons.map((y) => {
      const h = holdNetWorth(P, P.primary_rent, y, appr, marketRate, "full_rental", rentGrowth).netWorth;
      const s = investNetWorth(P, calcSell(P).netProceeds, y, marketRate);
      return h - s;
    });
    const sign0 = Math.sign(diffs[0]);
    let crossIdx = -1;
    for (let i = 1; i < diffs.length; i++) {
      if (Math.sign(diffs[i]) !== sign0 && Math.sign(diffs[i]) !== 0) {
        crossIdx = i;
        break;
      }
    }

    let crossText;
    if (crossIdx === -1) {
      crossText = `The Hold–Sell gap keeps the same sign across every horizon shown (${horizons[0]}–${hz} yrs).`;
    } else {
      crossText = `The Hold and Sell figures cross between year ${horizons[crossIdx - 1]} and year ${horizons[crossIdx]}.`;
    }

    return (
      `At ${hz} yrs: Hold is worth <b>${fmtDollars(hold)}</b>, Sell <b>${fmtDollars(sell)}</b> ` +
      `— a <b>${fmtDollars(gap)}</b> gap. ${crossText}`
    );
  }

  function redraw() {
    const appr = +document.getElementById("slider-appr").value / 100;
    const rentGrowth = +document.getElementById("slider-rent").value / 100;
    const marketRate = +document.getElementById("slider-market").value / 100;

    document.getElementById("val-appr").textContent = (appr * 100).toFixed(1).replace(/\.0$/, "") + "%";
    document.getElementById("val-rent").textContent = (rentGrowth * 100).toFixed(1).replace(/\.0$/, "") + "%";
    document.getElementById("val-market").textContent = (marketRate * 100).toFixed(1).replace(/\.0$/, "") + "%";

    document.getElementById("be-chart-live").innerHTML = buildSvg(appr, rentGrowth, marketRate);
    document.getElementById("be-readout").innerHTML = buildReadout(appr, rentGrowth, marketRate);
  }

  function init() {
    ["slider-appr", "slider-rent", "slider-market"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.addEventListener("input", redraw);
    });
    if (document.getElementById("be-chart-live")) redraw();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
}
