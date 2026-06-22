# Rent-vs-Sell — interpretation & decision framework

> **This is a decision aid, NOT part of the model output.** The report and `compute()`
> are deliberately data-only (CLAUDE.md rule 2 — no verdicts, so the downstream
> interpretation isn't anchored). This file is the *human* layer: how to read those
> numbers and decide. It lives outside the report on purpose. Every figure below is a
> reading of the committed model at the harold-ave inputs; re-derive with the sliders for
> your own assumptions.

---

## The one equation that explains everything

Each year you hold, ask a single question:

> **Is my walk-away cash growing faster than the market would grow it?**

Let **g(S)** = the year-over-year growth rate of your *after-fee, after-tax walk-away
cash* if you sold in year S. Then:

- **g(S) > the bar** → hold one more year (the house is out-compounding stocks).
- **g(S) < the bar** → sell now and invest (stocks win from here).

The horizon cancels out — both paths compound at the market after you're liquid — so the
choice is **g(S) vs. a fixed bar, year by year.** The optimal sell-year is the *last* year
g(S) is above the bar.

**The bar is NOT the headline market rate — it's a bit lower.** When you sell and reinvest,
those reinvested proceeds get taxed AGAIN at the final liquidation (cap-gains at year 30).
So the sell-and-reinvest path doesn't net the full 7.5% — the house's g(S) only has to beat
the *after-final-tax* market growth, a lower hurdle. Using the naive 7.5% bar makes the
crossing look ~1 year earlier than it really is (see the plateau below). This is the one
place the clean "g vs. market" intuition is approximate.

### Why g(S) decays (this is the whole engine)

Your equity grows each year from two sources — appreciation dollars on the *whole* house,
plus the principal you pay down — but that gain is measured against an equity base that is
**growing fast**, so the *percentage* falls every year. The on-paper (pre-fee, pre-tax)
equity math, year by year, at 4.5% appreciation:

| Year | Equity (start) | + Appreciation $ | + Principal paid | = Gain | YoY growth |
|---|---|---|---|---|---|
| →1 | 392,298 | 67,284 | 32,396 | 99,680 | **25.4%** |
| →2 | 491,977 | 70,312 | 33,132 | 103,444 | **21.0%** |
| →3 | 595,421 | 73,476 | 33,885 | 107,361 | **18.0%** |
| →4 | 702,782 | 76,782 | 34,656 | 111,438 | **15.9%** |
| →5 | 814,220 | 80,237 | 35,443 | 115,681 | **14.2%** |

The dollar gain *rises* (~$100k → $116k), but the equity base rises faster (392k → 814k),
so the rate slides 25% → 14% and keeps heading toward the unlevered 4.5%. That's the
leverage decay — pure arithmetic: a small early stake riding the whole house's gain,
diluted as the stake grows. (The 2.25% loan is fixed, so the *rate* is locked; what melts
is the *amount* of cheap leverage as you pay it down.)

**But the number that decides the question is lower than that on-paper equity.** Walk-away
cash subtracts selling costs (~6.4% of the home), the deferred cap-gains/recapture tax,
negative rental cash flow, and the reserve drag — all of which scale with the (growing)
home value. So the *real* g(S) (walk-away basis) runs ~20.6% → 15.6% → **7.3%** by year 3,
crossing the market hurdle around **year 2.5–3** on the marginal test. Both numbers decay
for the same leverage reason; walk-away is the one that matters, because it's the cash you
actually get.

The moment g(S) crosses below the bar, holding is value-destroying — **and it never crosses
back.** One crossing, one decision. (Caveat: the marginal "g vs. bar" crossing is ~year 3,
but the *full-horizon* economic optimum is later, ~year 5 — see "Why year 3" below for why
these differ.)

---

## The three regimes (at 7.5% market return)

Because g(S) is monotone and the market line is flat, where they cross depends on the
appreciation rate. That carves the whole decision into three bands:

| If home appreciation is… | Optimal move | Why |
|---|---|---|
| **below ~1.75%** | **Sell now.** | Even the early levered g is already below the bar. The house never out-earns stocks. |
| **~1.75% to ~5.18%** | **Sell within ~3 years.** | Levered g beats the bar for a few years, then decays below it. Economics alone gives a flat plateau (~yrs 3–6); the §121 deadline pulls the sharp answer to **year 3**. |
| **above ~5.18%** | **Hold for the long horizon.** | g(S) stays above the bar the whole way; the house out-compounds stocks indefinitely. |

(Thresholds are for the harold-ave inputs at 7.5% market; they move with the market-return
and rent sliders. Raise the market return → both thresholds rise → the bands shift toward
selling. They are *consequences* of g-vs-market, not magic constants.)

**The base case (4.5% appreciation, 7.5% market) sits in the middle band → sell within ~3 years.**

---

## Why "year 3" — and what's actually doing the work

It's tempting to say "the economics and the tax break coincidentally both point at year 3."
**That's not quite right, and the truer version matters.** Decomposing it:

1. **Pure economics (ignore §121 entirely): the optimum is a flat plateau around years
   3–6, peaking at ~year 5.** Holding 30-yr wealth (no tax break anywhere) runs
   2,121,984 (S=3) → 2,129,278 (S=4) → 2,136,533 (S=5) → 2,138,754 (S=6 peak) → then
   declines — all within ~0.3% of each other from 3 to 6. So on economics *alone* there is
   no sharp "year 3" answer; there's a broad, shallow plateau and you'd lean to ~5.
   (The naive "g(S) crosses 7.5% at ~year 2.5" undershoots because of the after-final-tax
   bar above: the real economic crossing sits later, ~year 5.)
2. **§121 is what sharpens it to year 3.** The $250k primary-residence exclusion survives
   only inside the 2-of-5-year window — through year 3. Sell in year 4 and you lose it, a
   one-time ~$75k hit (the "cliff"). That cliff is bigger than the ~$9k of economic upside
   from holding 3→5, so it drags the sharp optimum back to **3**: with the real §121 rule,
   S=3 jumps to 2,212,255, clearly the best.

So the honest statement: **the economic optimum is a shallow plateau (~yrs 3–6); the §121
deadline is doing the work that makes the answer a crisp "year 3."** They don't
independently coincide — the tax break drives it. The rising 1→3 side of the curve *is*
pure leverage (it rises with or without §121); but the *sharp top at 3* is the tax break,
not the economics.

---

## What the point-estimate "optimum" does NOT price — read before deciding

The model returns an *expected-value* answer. The middle-band strategy ("hold 2–3 years")
carries real costs that the single number understates:

### 1. Law-of-small-numbers risk (the big one)

A 30-year hold lets bad luck average out toward the modeled probabilities (15% vacancy,
5% eviction, 10% major repair per year). **A 3-year hold does not.** Over three years you
either draw the bad event or you don't — there's no averaging. The model charges the
*expected* drag (~$4.9k/yr); it does **not** charge the *variance*.

- Normal year: ~**$41k** out of pocket.
- A single bad year (long vacancy + eviction + a $40k repair): ~**$86k** out of pocket.

Concentrate the hold into 3 years and one unlucky draw can erase a big chunk of the
~$471k edge. The shorter the hold, the more the *expected* premium overstates the
*risk-adjusted* one. If you're not comfortable self-insuring a ~$86k bad year, the 2–3
year strategy is riskier than its point estimate looks.

### 2. The work

Three years of being a landlord: tenant placement, management oversight, maintenance
calls, the AB 1482 / just-cause-eviction compliance, and a tenant-occupied house being
harder to sell vacant later. The model prices *cash* costs (management %, vacancy), not
*your time and stress*. That's a real subtraction from the premium you have to make
yourself.

### 3. The leverage edge melts as you pay the loan down

The entire middle-band edge exists **because of the cheap 2.25% mortgage.** The rate itself
is *not* a risk — it's a **30-year fixed**, locked by contract, so it can't reset on you
(that's a point in the strategy's favor, not a fragility). The edge still fades, but for a
mechanical reason: **the *amount* of cheap leverage shrinks every month as you amortize.**
As equity grows and the borrowed slice shrinks, the same house-level gain rides a bigger
stake of your own money, so the levered g(S) decays toward the unlevered appreciation rate.
- The thing that *would* pull the thresholds up (toward selling sooner) is **less leverage
  to begin with** — a bigger down payment, or a cash-out refi that pulls equity back out
  and re-levers — not the fixed rate moving.
- If you would have to **sell stock to fund the $90k landlord reserve** (Scenario B), there's
  a small one-time cap-gains tax (~$8k–$25k depending on your embedded stock gain) that
  lands only on the Hold side. It's second-order vs. the headline gap, but it tilts slightly
  toward selling. (The ongoing reserve drag — earning 3% bonds instead of 7.5% market on
  that $90k — *is* already in the model.)

### 4. Forecast confidence

The whole answer pivots on **which appreciation band you believe.** The thresholds (1.75%,
5.18%) are close enough together that being one band off changes the action entirely. The
model can't tell you the future appreciation rate — it tells you *what each belief implies*.
Treat the bands as "how confident am I that SF appreciation lands in 2–5%?", not as a
prediction.

---

## How to actually decide

1. **Pick your appreciation belief** (the single most important input). Use the slider.
2. **Read which band it lands in** → sell now / hold ~2–3 yrs / hold long.
3. **If you're in the middle band, size the premium** (the Hold − Sell gap on the chart)
   against the three costs above:
   - Can I self-insure an ~$86k bad year over a *short* hold without it wrecking the thesis?
   - Is the per-year premium worth my time as a landlord?
   (The 2.25% loan is a 30-yr fixed, so the rate isn't a risk — it makes the early edge
   durable; only *less* leverage, e.g. a cash-out refi, would weaken it.)
4. **Stress-test the belief, not just the point.** Drag appreciation down a band and up a
   band. If the action is stable across your *plausible* range, decide with confidence. If
   it flips between bands inside that range, the honest answer is "it depends on appreciation
   more than on anything I can control" — which itself is the decision-relevant finding.

---

## One-line summary

> The choice reduces to **g(S) vs. an after-tax market bar**: hold while your levered,
> after-tax walk-away cash grows faster than stocks-net-of-final-tax, sell when it stops.
> On economics alone that's a shallow plateau around **years 3–6** (peak ~5); the **§121 tax
> deadline at year 3** is what sharpens the answer to a crisp "sell by year 3" in the 2–5%
> appreciation band. The point-estimate premium ignores the *concentrated* bad-year risk and
> the landlord work, which you must price yourself (the fixed 2.25% loan, by contrast, makes
> the early edge *durable* — not a risk).
