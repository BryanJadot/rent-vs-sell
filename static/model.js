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

function piMonthsInYear(P, yearIndex) {
  // Mirror of Model._pi_months_in_year: months of P&I actually paid in this year (the loan
  // ends after payments_left payments; 0 after payoff). Clamped to [0, 12].
  const remaining = P.payments_left - yearIndex * P.months_per_year;
  return Math.max(0, Math.min(P.months_per_year, remaining));
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
  // P&I only while the loan is active; after payoff the property carries no mortgage.
  const annualPi = P.monthly_pi * piMonthsInYear(P, yearIndex);
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
  // Depreciation runs for exactly DEPREC_YEARS (27.5), not 28 whole years: the final year
  // carries only its fractional remainder so total deductions == building_basis, matching
  // the recapture cap. (Mirror of model.py _taxable_rental_income.)
  const deprecYrsThisYear = Math.max(0.0, Math.min(1.0, P.deprec_years - yearIndex));
  const deprec = annualDepreciation(P) * deprecYrsThisYear;
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
  // Mirror of Model.calc_sell. netAfterTax (proceeds − closing cap-gains tax) is what the
  // SELL side actually invests — symmetric with the hold path paying its cap-gains tax at
  // the future sale. (On a loss, tax is 0 → netAfterTax === netProceeds.)
  const broker = P.home_value * P.broker_rate;
  const transfer = P.home_value * P.transfer_tax;
  const title = P.home_value * P.title_escrow;
  const total = broker + transfer + title;
  const net = P.home_value - total - P.mortgage_bal;
  const gain = P.home_value - total - P.cost_basis;
  const tax = gain <= P.cg_exclusion ? 0.0 : (gain - P.cg_exclusion) * P.cap_gains_rate;
  return { netProceeds: net, tax, netAfterTax: net - tax };
}

function oopBreakdown(P, monthlyRent) {
  // Mirror of Model.oop_breakdown — year-1 real cash flows (outflows negative).
  const r = calcRent(P, monthlyRent, 0);
  const rentIn = r.egi;
  const mortgageOut = -r.annualPi;
  const opexOut = -(r.fixed + r.mgmt + r.leasing);
  const taxBack = annualDeprecShield(P);
  return { rentIn, mortgageOut, opexOut, taxBack, net: rentIn + mortgageOut + opexOut + taxBack };
}

function riskScenarios(P, monthlyRent) {
  // Mirror of Model.risk_scenarios — bad-year incremental costs at this rent (signed,
  // outflows negative). Each event is added to the baseline independently (rows stand alone).
  // Incremental vacancy charges only the EXCESS months over the baseline 5% already netted
  // into `base` — same convention as expectedRiskDrag (mirror of Model.risk_scenarios).
  const base = oopBreakdown(P, monthlyRent).net;
  const extraVacancyCost = excessVacancyMonths(P) * monthlyRent;
  const worstExtra = extraVacancyCost + P.eviction_cost + netMajorRepair(P);
  return {
    baseline: base,
    extra_vacancy: -extraVacancyCost,
    eviction: -P.eviction_cost,
    major_repair: -netMajorRepair(P),
    worst_extra: -worstExtra,
    worst_total: base - worstExtra,
  };
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
  // Mirror of Model.invest_net_worth: gain taxed once at liquidation; only a POSITIVE gain
  // is taxed (a loss / negative principal gets no credit — see the Python docstring).
  const ending = netProceeds * Math.pow(1 + rate, years);
  const gain = ending - netProceeds;
  return ending - Math.max(0.0, gain) * P.cap_gains_rate;
}

function bestSell(P, years) {
  // Mirror of Model.best_sell — best of the invest-rate scenarios.
  const np = calcSell(P).netAfterTax;
  return Math.max(...P.invest_rates.map((r) => investNetWorth(P, np, years, r)));
}

function chartSec121(P, saleYear) {
  // Mirror of Model._chart_sec121: §121 keyed to the actual sale year, so the chart's HOLD
  // line and the SELL comparator use ONE exclusion rule (kept within the 2-of-5-yr window,
  // lost after) — they coincide at sell year 0 instead of differing by CG_EXCLUSION×rate.
  return saleYear <= P.sell_soon_max_years ? "within_3yr" : "full_rental";
}

function holdThenInvestNetWorth(P, monthlyRent, sellYear, horizon, appr, oppRate, rentGrowth) {
  // Mirror of Model.hold_then_invest_net_worth. Every point is after-fee, after-tax walk-away
  // cash (comparability — see the Python docstring). ONE PLAN, ONE §121 RULE: the whole line is
  // "I sell in year sellYear", so §121 keys off that ONE chosen sale year at every horizon (NOT
  // re-keyed to the horizon on the still-holding leg — that would inject a CG_EXCLUSION×rate
  // cliff at the 2-of-5-yr boundary on gain properties). Matches the SELL comparator, so the
  // lines coincide at sellYear 0.
  oppRate = oppRate === undefined ? P.primary_invest : oppRate;
  rentGrowth = rentGrowth === undefined ? P.rent_growth : rentGrowth;
  const sec121 = chartSec121(P, sellYear);
  // At/before the sell year you haven't reached your chosen sale yet — value = walk-away cash
  // if sold AT THE HORIZON, but under the planned sale year's §121 rule.
  if (horizon <= sellYear) {
    return holdNetWorth(P, monthlyRent, horizon, appr, oppRate, sec121, rentGrowth).netWorth;
  }
  // Sold at sellYear (after fee + tax), then invested — only new market gains taxed again.
  const nwAtSale = holdNetWorth(
    P, monthlyRent, sellYear, appr, oppRate, sec121, rentGrowth
  ).netWorth;
  return investNetWorth(P, nwAtSale, horizon - sellYear, oppRate);
}

function breakEvenAppreciation(P, years, oppRate, rentGrowth) {
  // Mirror of Model.break_even_appreciation — bisect appr s.t. HOLD ties SELL, both at oppRate.
  oppRate = oppRate === undefined ? P.primary_invest : oppRate;
  rentGrowth = rentGrowth === undefined ? P.rent_growth : rentGrowth;
  const target = investNetWorth(P, calcSell(P).netAfterTax, years, oppRate);
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
    chartSec121,
    holdThenInvestNetWorth,
    oopBreakdown,
    riskScenarios,
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

  // Hold & Sell wealth over CALENDAR time at the current slider values, for every year
  // 0..horizon. HOLD holds until sellYear then invests at the market rate; SELL sold at
  // year 0. Both move with every slider (incl. sell-year). Mirror of compute()'s
  // break_even_chart construction.
  function timeSeries(appr, rentGrowth, marketRate, rentLevel, sellYear) {
    const grid = C.yearGrid;
    const hold = grid.map(
      (y) => holdThenInvestNetWorth(P, rentLevel, sellYear, y, appr, marketRate, rentGrowth)
    );
    // SELL at the chosen market return — best of the invest scenarios is not used here
    // because the slider IS the market return; a single rate keeps the line interpretable.
    const sell = grid.map((y) => investNetWorth(P, calcSell(P).netAfterTax, y, marketRate));
    // Crossover year: first year whose sign(hold − sell) differs from year 1's (mirror of
    // the Python). Neutral fact (when the lines meet), not a verdict.
    const diffs = hold.map((h, i) => h - sell[i]);
    let crossover = null;
    if (diffs.length > 1) {
      const sign1 = diffs[1] >= 0 ? 1 : -1;
      for (let y = 2; y < diffs.length; y++) {
        const cur = diffs[y] >= 0 ? 1 : -1;
        if (cur !== sign1) {
          crossover = y;
          break;
        }
      }
    }
    return { grid, hold, sell, crossover };
  }

  // Mirror of render._break_even_svg coordinate mapping (time axis). Pure string-building;
  // the model numbers come from the engine above.
  function buildSvg(appr, rentGrowth, marketRate, rentLevel, sellYear) {
    const { grid, hold, sell, crossover } = timeSeries(appr, rentGrowth, marketRate, rentLevel, sellYear);
    const payoff = C.payoffYear;

    const W = C.W, Hh = C.Hh;
    const ml = C.ml, mr = C.mr, mt = C.mt, mb = C.mb;
    const x0 = ml, x1 = W - mr;
    const y0 = Hh - mb, y1 = mt;
    const axMin = grid[0], axMax = grid[grid.length - 1];

    const rawLo = Math.min(Math.min(...hold), Math.min(...sell));
    const rawHi = Math.max(Math.max(...hold), Math.max(...sell));
    const step = C.step;
    let yMin = Math.floor(rawLo / step) * step;
    let yMax = Math.ceil(rawHi / step) * step;
    if (yMax === yMin) yMax = yMin + step;

    const px = (t) => x0 + ((t - axMin) / (axMax - axMin)) * (x1 - x0);
    const py = (v) => y0 + ((v - yMin) / (yMax - yMin)) * (y1 - y0);

    const holdPts = grid.map((t, i) => `${px(t).toFixed(1)},${py(hold[i]).toFixed(1)}`).join(" ");
    const sellPts = grid.map((t, i) => `${px(t).toFixed(1)},${py(sell[i]).toFixed(1)}`).join(" ");
    const parts = [];

    const crossPhrase =
      crossover === null
        ? "the two curves do not cross over the years shown"
        : `the two curves cross around year ${crossover}`;
    parts.push(
      `<svg viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Hold and sell wealth over time, ` +
        `in years; ${crossPhrase}." ` +
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

    for (let t = axMin; t <= axMax + 1e-9; t += 5) {
      const xx = px(t);
      parts.push(`<text x="${xx.toFixed(1)}" y="${y0 + 18}" text-anchor="middle" fill="#666">${t}</text>`);
    }

    // Mortgage-payoff reference tick (explains the kink where P&I drops to 0).
    if (axMin <= payoff && payoff <= axMax) {
      const xx = px(payoff);
      parts.push(`<line x1="${xx.toFixed(1)}" y1="${y0}" x2="${xx.toFixed(1)}" y2="${y1}" stroke="#cdd6e5" stroke-dasharray="3 3"/>`);
      parts.push(
        `<text x="${xx.toFixed(1)}" y="${(y1 - 10).toFixed(1)}" text-anchor="middle" fill="#90a">loan paid off ~${payoff.toFixed(0)}y</text>`
      );
    }

    // Sell-year tick — where HOLD switches from property to invested cash (the curve bends).
    // Drawn distinctly (solid-ish accent) so it reads as the chosen action, not a reference.
    if (sellYear > axMin && sellYear < axMax) {
      const xx = px(sellYear);
      parts.push(`<line x1="${xx.toFixed(1)}" y1="${y0}" x2="${xx.toFixed(1)}" y2="${y1}" stroke="#c9a0d8" stroke-dasharray="2 2"/>`);
      parts.push(
        `<text x="${xx.toFixed(1)}" y="${(y0 + 32).toFixed(1)}" text-anchor="middle" fill="#a05fc0">sold yr ${sellYear}</text>`
      );
    }

    parts.push(`<polyline points="${sellPts}" fill="none" stroke="#2a7" stroke-width="2"/>`);
    parts.push(`<polyline points="${holdPts}" fill="none" stroke="#36c" stroke-width="2"/>`);

    if (crossover !== null && axMin <= crossover && crossover <= axMax) {
      const cx = px(crossover);
      const cy = py((hold[crossover] + sell[crossover]) / 2);
      parts.push(`<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="4" fill="#111"/>`);
      parts.push(
        `<text x="${cx.toFixed(1)}" y="${(cy - 10).toFixed(1)}" text-anchor="middle" fill="#111">cross ~yr ${crossover}</text>`
      );
    }

    parts.push(`<text x="${(x1 - 6).toFixed(1)}" y="${(py(hold[hold.length - 1]) - 8).toFixed(1)}" text-anchor="end" fill="#36c">Hold</text>`);
    parts.push(`<text x="${(x1 - 6).toFixed(1)}" y="${(py(sell[sell.length - 1]) + 16).toFixed(1)}" text-anchor="end" fill="#2a7">Sell now</text>`);
    parts.push(
      `<text x="${((x0 + x1) / 2).toFixed(0)}" y="${Hh - 4}" text-anchor="middle" fill="#444">Year</text>`
    );
    parts.push("</svg>");
    return parts.join("");
  }

  // Per-year cash-flow chart. HOLD's economic cash flow each year (rent − costs − P&I that
  // year + shield − risk drag), crossing $0 and turning positive at payoff; SELL flat at $0
  // (proceeds reinvested, nothing withdrawn). Mirror of render._cashflow_svg. NOTE: this
  // depends only on rent growth — appreciation and market return don't change the yearly
  // cash in/out of the property, so only the rent slider moves this chart.
  function buildCashflowSvg(rentGrowth, rentLevel) {
    const grid = C.cashflowYearGrid;
    const hold = grid.map((y) => yearCashFlow(P, rentLevel, y, rentGrowth));
    const payoff = C.payoffYear;

    const W = C.W, Hh = C.Hh;
    const ml = C.ml, mr = C.mr, mt = C.mt, mb = C.mb;
    const x0 = ml, x1 = W - mr;
    const y0 = Hh - mb, y1 = mt;
    const axMin = grid[0], axMax = grid[grid.length - 1];

    const step = C.cashflowStep;
    const rawLo = Math.min(Math.min(...hold), 0.0);
    const rawHi = Math.max(Math.max(...hold), 0.0);
    let yMin = Math.floor(rawLo / step) * step;
    let yMax = Math.ceil(rawHi / step) * step;
    if (yMax === yMin) yMax = yMin + step;

    const px = (t) => x0 + ((t - axMin) / (axMax - axMin)) * (x1 - x0);
    const py = (v) => y0 + ((v - yMin) / (yMax - yMin)) * (y1 - y0);
    const holdPts = grid.map((t, i) => `${px(t).toFixed(1)},${py(hold[i]).toFixed(1)}`).join(" ");
    const zeroY = py(0.0);
    const parts = [];

    parts.push(
      `<svg viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Hold per-year cash flow over the ` +
        `holding period; negative early, turning positive after the mortgage is paid off; ` +
        `the sell line is flat at zero." style="width:100%;height:auto;font:12px system-ui,sans-serif">`
    );
    parts.push(`<line x1="${x0}" y1="${y0}" x2="${x0}" y2="${y1}" stroke="#bbb"/>`);

    const nSteps = Math.round((yMax - yMin) / step);
    for (let i = 0; i <= nSteps; i++) {
      const v = yMin + i * step;
      const yy = py(v);
      parts.push(`<line x1="${x0}" y1="${yy.toFixed(1)}" x2="${x1}" y2="${yy.toFixed(1)}" stroke="#eee"/>`);
      const k = v / 1000;
      const label = k < 0 ? `−$${Math.abs(k).toFixed(0)}k` : `$${k.toFixed(0)}k`;
      parts.push(`<text x="${x0 - 6}" y="${(yy + 4).toFixed(1)}" text-anchor="end" fill="#666">${label}</text>`);
    }

    for (let t = axMin; t <= axMax + 1e-9; t += 5) {
      parts.push(`<text x="${px(t).toFixed(1)}" y="${y0 + 18}" text-anchor="middle" fill="#666">${t}</text>`);
    }

    if (axMin <= payoff && payoff <= axMax) {
      const xx = px(payoff);
      parts.push(`<line x1="${xx.toFixed(1)}" y1="${y0}" x2="${xx.toFixed(1)}" y2="${y1}" stroke="#cdd6e5" stroke-dasharray="3 3"/>`);
      parts.push(`<text x="${xx.toFixed(1)}" y="${(y1 - 10).toFixed(1)}" text-anchor="middle" fill="#90a">loan paid off ~${payoff.toFixed(0)}y</text>`);
    }

    parts.push(`<line x1="${x0}" y1="${zeroY.toFixed(1)}" x2="${x1}" y2="${zeroY.toFixed(1)}" stroke="#2a7" stroke-width="2"/>`);
    parts.push(`<polyline points="${holdPts}" fill="none" stroke="#36c" stroke-width="2"/>`);
    parts.push(`<text x="${(x0 + 6).toFixed(1)}" y="${(py(hold[0]) + 16).toFixed(1)}" text-anchor="start" fill="#36c">Hold</text>`);
    parts.push(`<text x="${(x1 - 6).toFixed(1)}" y="${(zeroY - 8).toFixed(1)}" text-anchor="end" fill="#2a7">Sell now ($0)</text>`);
    parts.push(`<text x="${((x0 + x1) / 2).toFixed(0)}" y="${Hh - 4}" text-anchor="middle" fill="#444">Years held (per-year cash in/out of pocket)</text>`);
    parts.push("</svg>");
    return parts.join("");
  }

  // Neutral readout: figures only — gap at the longest horizon + crossover year.
  // No "you should"/"better"/"win" (CLAUDE.md rule 2).
  function buildReadout(appr, rentGrowth, marketRate, rentLevel, sellYear) {
    const { grid, hold, sell, crossover } = timeSeries(appr, rentGrowth, marketRate, rentLevel, sellYear);
    const hz = grid[grid.length - 1];
    const holdHz = hold[hold.length - 1];
    const sellHz = sell[sell.length - 1];
    const gap = Math.abs(holdHz - sellHz);

    const crossText =
      crossover === null
        ? `The Hold and Sell curves keep the same order across every year shown (${grid[0]}–${hz}).`
        : `The two curves cross around year ${crossover}.`;

    // Ground the future-dollar gap in today's purchasing power: a dollar `hz` years out is
    // worth 1/(1+inflation)^hz today (same factor the report's "worth ~X today" line uses).
    const todayGap = gap / Math.pow(1 + P.inflation_rate, hz);

    return (
      `At ${hz} yrs: Hold is worth <b>${fmtDollars(holdHz)}</b>, Sell <b>${fmtDollars(sellHz)}</b> ` +
      `— a <b>${fmtDollars(gap)}</b> gap (about <b>${fmtDollars(todayGap)}</b> in today's money). ${crossText}`
    );
  }

  // Live table: Hold and Sell net worth at each reported horizon, at the current slider
  // values, plus their gap. Figures only (Rule 2) — the gap is a signed magnitude with no
  // good/bad coloring, since "which side is larger" is not a verdict this report makes.
  function buildHorizonTable(appr, rentGrowth, marketRate, rentLevel, sellYear) {
    const horizons = P.horizons;
    const head = horizons.map((y) => `<th>${y}-yr</th>`).join("");
    // HOLD = hold until the chosen sell year, then invest the proceeds — same wealth-over-time
    // basis as the chart, so the table and chart tell one coherent story.
    const holdAt = (y) =>
      holdThenInvestNetWorth(P, rentLevel, sellYear, y, appr, marketRate, rentGrowth);
    const holdCells = horizons.map((y) => `<td>${fmtDollars(holdAt(y))}</td>`).join("");
    const sellCells = horizons
      .map((y) => `<td>${fmtDollars(investNetWorth(P, calcSell(P).netAfterTax, y, marketRate))}</td>`)
      .join("");
    const gapCells = horizons
      .map((y) => {
        const d = holdAt(y) - investNetWorth(P, calcSell(P).netAfterTax, y, marketRate);
        // signed magnitude, neutral: "+" = Hold larger, "−" = Sell larger (a label, not a judgment)
        const sign = d >= 0 ? "+" : "−";
        return `<td>${sign}$${Math.abs(Math.round(d)).toLocaleString("en-US")}</td>`;
      })
      .join("");
    return (
      `<thead><tr><th>If you sell in year ${sellYear}</th>${head}</tr></thead>` +
      `<tbody>` +
      `<tr class="primary"><td>Hold (keep &amp; rent, then invest)</td>${holdCells}</tr>` +
      `<tr class="sell"><td>Sell now + invest</td>${sellCells}</tr>` +
      `<tr class="total"><td>Hold − Sell</td>${gapCells}</tr>` +
      `</tbody>`
    );
  }

  const fmtSigned = (v) =>
    (v < 0 ? "−" : "+") + "$" + Math.abs(Math.round(v)).toLocaleString("en-US");

  // Year-1 cash breakdown at one rent (mirror of render._cashflow_table_html).
  function buildCashflowTable(rentLevel) {
    const oop = oopBreakdown(P, rentLevel);
    const rt = calcRent(P, rentLevel, 0);
    const rows = [
      ["Rent collected (net of vacancy)", oop.rentIn],
      ["Mortgage payment (principal &amp; interest)", oop.mortgageOut],
      ["Property tax", -rt.propTax],
      ["Insurance", -P.insurance],
      ["Repairs / maintenance", -P.repairs],
      ["Management &amp; leasing", -(rt.mgmt + rt.leasing)],
      [
        'Yearly depreciation tax break <span class="sub">(none now — suspended at income &gt;$' +
          (P.passive_loss_magi_limit / 1000).toLocaleString("en-US") +
          "k, used at sale; see §3)</span>",
        oop.taxBack,
      ],
    ];
    let body = "";
    for (const [label, v] of rows) {
      const cell =
        v === 0
          ? '<td class="sub">$0</td>'
          : `<td class="${v > 0 ? "num-good" : "num-bad"}">${fmtSigned(v)}</td>`;
      body += `<tr><td>${label}</td>${cell}</tr>`;
    }
    const net = oop.net;
    body +=
      `<tr class="total"><td>Net cash flow / yr</td><td class="num-bad">${fmtSigned(net)}</td></tr>` +
      `<tr class="total"><td>…per month</td><td class="num-bad">${fmtSigned(net / P.months_per_year)}</td></tr>`;
    const rk = (rentLevel / 1000)
      .toLocaleString("en-US", { maximumFractionDigits: 2 })
      .replace(/\.?0+$/, "");
    return `<thead><tr><th>Cash item (at $${rk}k/mo)</th><th>Year 1</th></tr></thead><tbody>${body}</tbody>`;
  }

  // Bad-year cost table at one rent (mirror of render._badyear_table_html). No running-total
  // column — each event shows only its own extra cost (events are independent; they don't
  // stack or sum down). Baseline and the all-three worst case are their own framed rows.
  function buildBadYearTable(rentLevel) {
    const r = riskScenarios(P, rentLevel);
    const neg = (v) => `−$${Math.abs(Math.round(v)).toLocaleString("en-US")}`;
    const events = [
      ["A long vacancy (above normal turnover)", r.extra_vacancy],
      ["A non-paying tenant + eviction", r.eviction],
      ["A major repair (roof/foundation), net of tax", r.major_repair],
    ];
    let body =
      `<tr><td>A <b>normal</b> year already costs</td>` +
      `<td class="num-bad">${neg(r.baseline)}</td></tr>` +
      `<tr><td colspan="2" class="sub">Any <b>one</b> bad event that year adds, on its own ` +
      `(they don't stack):</td></tr>`;
    for (const [label, hit] of events) {
      body += `<tr><td>&nbsp;&nbsp;${label}</td><td class="num-bad">${neg(hit)}</td></tr>`;
    }
    body +=
      `<tr class="total"><td>All <b>three</b> at once → that year costs</td>` +
      `<td class="num-bad">${neg(r.worst_total)}</td></tr>`;
    const rk = (rentLevel / 1000)
      .toLocaleString("en-US", { maximumFractionDigits: 2 })
      .replace(/\.?0+$/, "");
    return (
      `<thead><tr><th>At $${rk}k/mo</th><th>Out of pocket</th></tr></thead><tbody>${body}</tbody>`
    );
  }

  function redraw() {
    const appr = +document.getElementById("slider-appr").value / 100;
    const rentGrowth = +document.getElementById("slider-rent").value / 100;
    const marketRate = +document.getElementById("slider-market").value / 100;
    const rentLevel = +document.getElementById("slider-rentlevel").value;
    const sellYear = +document.getElementById("slider-sellyear").value;

    document.getElementById("val-appr").textContent = (appr * 100).toFixed(1).replace(/\.0$/, "") + "%";
    document.getElementById("val-rent").textContent = (rentGrowth * 100).toFixed(1).replace(/\.0$/, "") + "%";
    document.getElementById("val-market").textContent = (marketRate * 100).toFixed(1).replace(/\.0$/, "") + "%";
    document.getElementById("val-rentlevel").textContent = "$" + rentLevel.toLocaleString("en-US") + "/mo";
    document.getElementById("val-sellyear").textContent = "yr " + sellYear;

    // Every live element is keyed by id; some live in §1, some in §2 — the global slider
    // bar drives them all wherever they sit. Each `if` guards against an absent element.
    const setHtml = (id, html) => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = html;
    };
    setHtml("be-table-live", buildHorizonTable(appr, rentGrowth, marketRate, rentLevel, sellYear));
    setHtml("be-chart-live", buildSvg(appr, rentGrowth, marketRate, rentLevel, sellYear));
    setHtml("be-readout", buildReadout(appr, rentGrowth, marketRate, rentLevel, sellYear));
    setHtml("cashflow-chart-live", buildCashflowSvg(rentGrowth, rentLevel));
    setHtml("be-cashflow-table-live", buildCashflowTable(rentLevel));
    setHtml("be-badyear-table-live", buildBadYearTable(rentLevel));
  }

  function init() {
    ["slider-appr", "slider-rent", "slider-market", "slider-rentlevel", "slider-sellyear"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.addEventListener("input", redraw);
    });
    if (document.getElementById("be-chart-live")) redraw();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
}
