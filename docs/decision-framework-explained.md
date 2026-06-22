# Should you rent out a house or sell it? — explained from scratch

*No background needed. We'll build up every idea, and do the math together.*

---

## Part 0: The setup (the actual situation)

Imagine you own a house worth about **$1.5 million**. You don't live in it anymore. You
have two choices:

- **SELL it now**, take the cash, and put that money into the stock market.
- **HOLD it**: rent it out to tenants (they pay you every month), and sell it later.

Which makes you richer in the long run? That's the whole question. To answer it we need a
few ideas first. Don't worry if you've never thought about any of this — we start at zero.

---

## Part 1: Five ideas you need first

### Idea 1: Money grows if you invest it

If you put money in the stock market, it grows over time — historically about **7% a
year** on average. "7% a year" means each year your money becomes 1.07× as big.

The magic part is **compounding**: you earn growth *on your previous growth*. $100 doesn't
become $170 after 10 years — it becomes about **$197**, because each year's 7% is taken on
a bigger and bigger pile.

> **Math check:** $100 growing 7%/year for 10 years = $100 × (1.07)¹⁰.
> 1.07¹⁰ ≈ 1.97, so ≈ **$197**. For 30 years: 1.07³⁰ ≈ 7.6, so $100 → **$760**.
> Time is doing a *lot* of the work. Remember that — it comes back later.

So whichever choice eventually turns into cash, that cash then grows in the market. This is
the "fair comparison" trick: once *both* choices are just money sitting in the market, they
grow the same way from then on. So the real question is only **how much cash does each
choice hand you, and when?**

### Idea 2: A house can grow in value too ("appreciation")

Houses tend to get more valuable over time. If a house goes up about **4.5% a year**, we
say it *appreciates* 4.5%/year. Same compounding idea as the stock market, just a different
(usually smaller) rate.

Right away you might think: "Stocks grow 7%, houses grow 4.5%, so just sell and buy stocks,
right?" **Hold that thought** — there's a twist (Idea 4) that flips it.

### Idea 3: A mortgage = you only paid for *part* of the house

Almost nobody buys a house with their own cash. You borrow most of it from a bank. That
loan is a **mortgage**. So out of a $1.5M house, you might only actually own about **$390k
of it** — your slice is called your **equity**. The bank "owns" the other ~$1.1M (the loan)
until you pay it back.

You pay the bank back slowly every month, plus interest. The interest rate on this
particular loan is very low — **2.25%/year**, and it's a **30-year fixed**, meaning that
rate is locked by contract and can *never* go up. (A loan rate below the stock market's 7%
is basically cheap money. Keep that in mind — it's the whole engine.)

### Idea 4: Leverage — the twist that makes houses powerful

Here's the key trick, and it's worth slowing down for.

The house grows in value on its **whole price** ($1.5M), but **your slice is only $390k.**
So when the house goes up 4.5%, the *dollars* you gain are 4.5% of the whole thing:

> 4.5% of $1.5M ≈ **$67,000** of appreciation.

On top of that, each year a chunk of your mortgage payment goes to *paying down the loan*
(~$32,000/year early on), which also becomes your equity. So your equity grows by about
**$67k + $32k ≈ $99k** in year one.

Now measure that gain against *your* $390k slice:

> $99,000 ÷ $390,000 ≈ **25%**.

**Whoa.** The house only went up 4.5%, but *your money* went up ~25%, because you're riding
the gain on the *whole* house while only having put down a sliver. That's called
**leverage** — borrowed money multiplying your gains. (It multiplies losses too, but set
that aside.) This is why "houses grow slower than stocks" doesn't settle the question.

### Idea 5: Taxes (the government takes a cut when you cash out)

When you sell something for a profit, the government taxes the profit. Three pieces matter
here — the first is simple, but the second and third are the ones that end up deciding the
whole answer, so don't skim them.

- **Capital-gains tax:** sell something for more than you paid, and you owe tax on the
  profit — here, about **37%** of it.
- **A big home tax break that expires:** there's a special rule that lets you keep a chunk
  of your home's profit tax-free — **but only if you sell within about 3 years.** Sell in
  year 4 or later and it's gone. For this house, missing it costs about **$75,000** (we'll
  see exactly where that comes from in Part 3). The one thing to remember: **a valuable tax
  break that disappears after year 3.**
- **The sneaky one — stocks get taxed at the end too.** If you SELL now and put the cash in
  stocks, those stock gains get taxed (37%) when you eventually cash out. So the "sell and
  invest" path doesn't really keep the full 7%/year — after that final tax it's more like
  **~6%/year**. That matters because it's the number the house has to beat: the real bar is
  **~6%, not 7%.** Hold this thought; it comes back in Part 3.

That's all the background. Now we can actually answer the question.

---

## Part 2: Why holding gets worse over time (the core insight)

**The short version:** holding is amazing at first (your money grows ~20%/year!) but that
fades fast every year, and by year 3 it's barely beating the stock market. The rest of this
part shows why — with the numbers, if you want them.

Remember that ~25% leveraged return in year one? Watch what happens to it. Here's how your
equity builds, year by year, at 4.5% appreciation:

| Year | Equity at start | + Appreciation | + Loan paid down | = Gain | **Growth that year** |
|---|---|---|---|---|---|
| 1 | $392,298 | $67,284 | $32,396 | $99,680 | **25.4%** |
| 2 | $491,977 | $70,312 | $33,132 | $103,444 | **21.0%** |
| 3 | $595,421 | $73,476 | $33,885 | $107,361 | **18.0%** |
| 4 | $702,782 | $76,782 | $34,656 | $111,438 | **15.9%** |
| 5 | $814,220 | $80,237 | $35,443 | $115,681 | **14.2%** |

Look closely: the **dollar gain actually keeps rising** ($99k → $116k). So why does the
*percentage* fall? Because your **equity base is growing even faster** ($392k → $814k). The
same-ish gain, divided by a bigger and bigger pile of your own money, is a smaller percent.

That's the whole engine: **leverage is strongest when your slice is smallest.** As you own
more of the house outright, the magic fades and your growth rate slides down toward the
plain 4.5% the house itself earns.

> **Why the loan being fixed doesn't save it:** the rate is locked, yes — but the *amount*
> of cheap borrowed money shrinks every month as you pay it off. The boost comes from the
> *size* of the loan, and that's melting whether the rate moves or not.

### The catch: "on paper" isn't what you'd pocket

The growth above (25% → 14%) is your equity **on paper** — the value if you *don't* sell. But
the moment you actually sell, you lose a chunk to **selling fees (~6.4%)**, the **tax** on your
gain, and the fact the **rent never quite covered the mortgage**. What you'd really **walk away
with** is a lot lower — and it grows a lot slower. Here are both side by side:

| Year | Growth "on paper" (don't sell) | Growth of your real walk-away cash |
|---|---|---|
| 1 | 25.4% | **~20.6%** |
| 2 | 21.0% | **~15.6%** |
| 3 | 18.0% | **~7.3%** |
| 4 | 15.9% | **~7.2%** |
| 5 | 14.2% | **~6.9%** |

Notice the right column is **roughly half** the left — and it's the right one that matters,
because the decision is whether to *sell*, and selling is what triggers those costs. From here
on, "your growth" means the **walk-away** number: ~20% early, crashing to **~7% by year 3**,
still sliding after.

### The rule

Each year, ask: **is my cash growing faster than stocks would grow it?** And remember from
Idea 5 — the stocks side isn't really 7%, it's about **6%** after that final tax. So:

> **Keep holding while your cash grows faster than ~6%/year. Sell once it drops below — and
> it never climbs back up.**

---

## Part 3: So when do you sell? Two different answers, and why

**The short version:** on the money math alone there's no single best year — anywhere from 3
to 6 is basically a tie. What breaks the tie is a tax break that expires at year 3. So: **sell
by year 3.**

Here's how we get there — and it's easy to get wrong, because there are really *two* separate
questions hiding in "when do you sell," and they have *different* answers.

### Answer A — ignore the tax break for a second: there's no single best year

If there were **no tax break** at all, when would you sell? Let's just compute your
final wealth at 30 years for each possible sell-year, and see which is biggest:

| Sell in year… | Your wealth at 30 years (no tax break) |
|---|---|
| 2 | $2,121,984 |
| 3 | $2,129,278 |
| 4 | $2,136,533 |
| **5** | **$2,138,754** ← biggest |
| 6 | $2,136,585 |

**Why are years 3–6 nearly identical?** Think about what holding *one more year* does. It's a
race between two things:

- **Hold the extra year:** your walk-away cash grows by that year's rate (from Part 2's
  walk-away column).
- **Sell instead and put the cash in stocks:** it grows by the ~6% market bar.

Whichever is faster wins that year. Early on it's no contest — your cash is growing 20%, miles
above 6%, so holding is obviously right. But by **year 3 the walk-away growth has fallen to
~7%** — barely above the ~6% bar. So holding year 4, year 5, year 6 each helps *just a hair*.
That's why the final-wealth numbers barely move: each extra year is a near-tie. There's no
sharp "best year" — it's a **flat plateau.** (Year 5 is the biggest number, but only by a
rounding error.)

So on **pure money math alone**, the answer is a vague "somewhere around year 3 to 6 — it
barely matters which."

### Answer B — now add the tax break: the answer snaps to year 3

The tax break changes everything because of the **cliff** at year 3→4. Watch what happens to
the *real* numbers (with the tax break included) right at the boundary:

| Sell in year… | Your wealth at 30 years (**with** the tax break) |
|---|---|
| 3 | **$2,212,255** ← biggest |
| 4 | $2,136,533 |
| 5 | $2,138,754 |

Selling in **year 3** is worth **$2,212,255** — about **$75,000 more** than year 4. That $75k
is exactly the tax break you lose by waiting one more year. Compare that to Answer A, where
the *most* you could gain by picking the perfect year was a few thousand dollars. The tax
break (~$75k) is worth about *eight times* more than the whole "find the best year" question
(~$9k) — so it wins, and the answer is year 3.

**So here's the honest picture:**

> The pure economics give a *flat plateau* around years 3–6 (slightly best at 5). It's the
> **tax break, and only the tax break,** that sharpens the answer into a crisp **"sell by
> year 3."** The two don't magically line up — the tax deadline is doing the work.

The early rise over years 1 to 3 is the leverage from Part 2 — that part is real money math.
But the *exact* "year 3" punchline comes from the tax rule, not from the leverage.

---

## Part 4: It's not always "year 3" — it depends on appreciation

Everything above used 4.5% appreciation. Change that guess and the answer moves into one of
three buckets:

1. **House barely appreciates (under ~2%/year):** even the early leverage boost can't beat
   the (~6%, after-tax) stock bar. → **Just sell now.**
2. **House appreciates moderately (~2% to ~5%/year):** leverage wins early, then fades to a
   plateau — and the tax break makes year 3 the pick. → **Sell within ~3 years.**
   ← *this house, at 4.5%, is here.*
3. **House appreciates fast (over ~5%/year):** the house out-grows stocks the *whole* time
   and never drops below the bar. → **Hold onto it for the long haul.**

So before anything else, you have to guess **which bucket your house is in.** That guess
(the appreciation rate) is the single most important number in the whole decision.

> *Where do those ~2% and ~5% walls come from?* They're the appreciation rates where your
> leveraged house-growth crosses the after-tax stock bar. If stocks grew faster, both walls
> shift up and you'd lean more toward selling.

---

## Part 5: The catch — the money math is only the *average* case

Everything so far is an *average-case* answer. Real life is messier, and these are costs the
clean numbers hide. You weigh them yourself.

### Catch 1: Bad luck doesn't have time to average out (the biggest one)

Being a landlord has random bad events: a tenant stops paying and you have to evict them, the
house needs a surprise $40,000 repair, or it sits empty for months with no rent. On average
these cost a predictable amount. **But "on average" only works over a long time.**

Think of a coin. Flip it 1,000 times → you'll get close to 50% heads. Flip it **3 times** →
you might get all tails. Bad luck *averages out over many years, but not over just 3.* And
the answer here is "sell in ~3 years" — a *short* hold, so you're rolling the dice only a few
times. One bad year can be brutal:

- Even a *normal* year already costs you about **$41,000** out of pocket — the rent doesn't
  fully cover the mortgage and expenses.
- A *bad* year — empty house + eviction + big repair at once — runs about **$86,000**, roughly
  double.

If that one bad year lands during your short hold, it eats a big chunk of the profit. **The
money math only charges you the *average* bad-luck cost; the *risk* of drawing one brutal year
in a short window is yours to judge.**

### Catch 2: It's actual work

Three years of being a landlord isn't passive: tenants, repairs, paperwork, legal rules about
renting and evicting, and the headache of selling a house with people living in it. The math
counts the *cash* costs, not your *time and stress*. Subtract that yourself.

### Catch 3: You might have to dip into savings to be a landlord

Landlords keep an emergency fund (here, ~**$90,000**) for those bad years. If you don't have
that cash lying around, you'd have to sell some stocks to raise it — and selling stocks
triggers a little tax. It's a small extra cost, but it lands only on the "hold" side, nudging
things slightly toward selling. (The ongoing cost — that $90k sitting safe instead of in the
market — is already in the math.)

---

## Part 6: So how do you actually decide?

1. **Make your best guess for how fast the house will appreciate.** This is the big one.
2. **Find your bucket:**
   - Under ~2%/year → **sell now.**
   - ~2% to ~5%/year → **sell within ~3 years** (grab the leverage years *and* the tax
     break before it expires).
   - Over ~5%/year → **hold long-term.**
3. **If you land in the middle bucket, sanity-check it against the catches:**
   - Could I survive an ~$86,000 bad year over a *short* hold without it wrecking my profit?
   - Is the extra money worth a few years of being a landlord?
4. **Test how sure you are.** Try a slightly higher and slightly lower appreciation guess. If
   you land in the same bucket either way, you can decide with confidence. If a small change
   flips the bucket, then the honest answer is "it depends on the housing market more than on
   anything I can control" — and knowing *that* is itself the real takeaway.
