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

- **g(S) > market return** → hold one more year (the house is out-compounding stocks).
- **g(S) < market return** → sell now and invest (stocks win from here).

The horizon cancels out — both paths compound at the market after you're liquid — so the
choice is purely **g(S) vs. the market return, year by year.** The optimal sell-year is
the *last* year g(S) is still above the market.

### Why g(S) decays (this is the whole engine)

g(S) starts high and falls monotonically toward the unlevered appreciation rate, because
the two forces that make it high are temporary:

1. **Leverage on appreciation.** The house appreciates on its *full* value (~$1.5M) while
   you only staked your *equity* (~$390k). At 4.5% appreciation that's ~16%/yr on your
   equity in the early years. As equity grows, the levered boost blends down toward the
   raw 4.5%.
2. **Principal paydown at a cheap rate.** Early payments convert 2.25% mortgage interest
   into equity fast. Once the loan is mostly paid (~year 26), this contribution vanishes.

So g(S) is high early (both forces firing), then decays. The moment it crosses below the
market return, holding is value-destroying — **and it never crosses back.** One crossing,
one decision.

---

## The three regimes (at 7.5% market return)

Because g(S) is monotone and the market line is flat, where they cross depends on the
appreciation rate. That carves the whole decision into three bands:

| If home appreciation is… | Optimal move | Why |
|---|---|---|
| **below ~1.75%** | **Sell now.** | Even the early levered g is already below the market. The house never out-earns stocks. |
| **~1.75% to ~5.18%** | **Hold ~2–3 years, then sell.** | Early levered g beats the market for a few years, then decays below it. Sell as that edge expires. |
| **above ~5.18%** | **Hold for the long horizon.** | g(S) stays above the market the whole way; the house out-compounds stocks indefinitely. |

(Thresholds are for the harold-ave inputs at 7.5% market; they move with the market-return
and rent sliders. Raise the market return → both thresholds rise → the bands shift toward
selling. They are *consequences* of g-vs-market, not magic constants.)

**The base case (4.5% appreciation, 7.5% market) sits in the middle band → hold ~2–3 years.**

---

## The §121 coincidence — why "2–3 years" specifically

Two *independent* clocks both point at year 3, which is why the peak is so sharp:

1. **Economic clock:** at sub-5% appreciation, g(S) crosses the market return around year 3
   anyway (the levered edge is expiring).
2. **Tax clock:** the §121 primary-residence cap-gains exclusion ($250k) survives only
   while you're inside the 2-of-5-year window — i.e. through year 3. Sell in year 4 and you
   lose it, a one-time ~$75k hit (the "cliff" in the chart).

They reinforce: the year your levered edge runs out is also the last year you keep the tax
exclusion. **Don't mistake this for "2–3 years is a universal sweet spot."** It's a
coincidence of *these* inputs. The rising 1→3 side of the curve is pure
leverage-on-appreciation (it would rise even with no §121); §121 just sharpens the top and
makes year 3 the hard deadline rather than a soft optimum.

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

### 3. It's leverage-fragile

The entire middle-band edge exists **because of the 2.25% mortgage.** It is not robust to
that assumption:
- A higher mortgage rate, less leverage, or a cash-out refi shrinks early g(S) → pulls the
  thresholds up → pushes you toward selling sooner.
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
   - Is my leverage assumption (the 2.25% loan) actually going to persist?
4. **Stress-test the belief, not just the point.** Drag appreciation down a band and up a
   band. If the action is stable across your *plausible* range, decide with confidence. If
   it flips between bands inside that range, the honest answer is "it depends on appreciation
   more than on anything I can control" — which itself is the decision-relevant finding.

---

## One-line summary

> The choice reduces to **g(S) vs. the market return**: hold while your levered, after-tax
> walk-away cash grows faster than stocks, sell when it stops. For this house that puts the
> economic and the §121-tax deadlines both around **year 3 in the 2–5% appreciation band** —
> but the point-estimate premium ignores the *concentrated* bad-year risk, the landlord work,
> and its dependence on cheap leverage, all of which you must price yourself.
