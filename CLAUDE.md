# CLAUDE.md — working notes for this project

Guidance for making changes here without breaking the design. Read this before editing.

## What this is

A rent-vs-sell financial model for a house. It computes whether selling now and
investing beats renting it out and selling later, on an apples-to-apples after-tax
basis, and renders an HTML report (data only — no interpretation; see rule 2).

## Architecture (three layers, one-way dependencies)

```
properties/*.toml   per-house inputs (data only)
        │  loaded by assumptions.load_property() → Property dataclass
        ▼
assumptions.py      shared market/tax/policy constants + Property loader
        ▼
model.py            Model class: all financial math; compute() → dict
        ▼
render.py           presentation: builds HTML (templates/) + text from the model
```

**The dependency arrow only points down.** `model` imports from `assumptions`;
`render` imports from `assumptions` and `model`. Nothing imports `render`. Never make
`model` or `assumptions` depend on `render` or on presentation concerns.

## The cardinal rules

1. **No math in `render.py`.** If you're computing a dollar figure or a comparison,
   it belongs in `model.py`. render only formats and arranges; every number comes from
   `model.compute()` or the model's calc methods — so the page can never contradict the
   tables.

2. **No interpretation in the generated output.** The report (and `compute()`) contain
   DATA ONLY: figures, sensitivities, and explanations of *terms and mechanics* (what
   depreciation recapture is; why both sides are taxed symmetrically; what a sensitivity
   row varies). They must NOT contain a verdict, recommendation, "which is better,"
   beats/trails comparison, edge/upside/downside aggregate, win-count, or
   questions/next-steps. *Why:* interpretation is produced by a separate downstream
   prompt, and we don't want that prompt anchored by conclusions we baked in. *How to
   apply:* keep tables and term/mechanic explanations; if a sentence states or implies
   which choice comes out ahead, it doesn't belong here. This also covers code comments
   and docstrings that a future agent would read — explain the *mechanics*, not the
   conclusion. Neutral *factual* notes (legal/process facts like AB 1482, just-cause
   eviction) are allowed as facts, not advice. (Removed: the old `verdict` block,
   `_compare`, `headline_verdict`/`take`/`bet_framing`, and the interpretation page.)

3. **No magic numbers / no duplicated values.** Every rate, threshold, or input has
   exactly one definition:
   - Per-house values → the property's TOML (`properties/*.toml`).
   - Shared market/tax/policy values → `assumptions.py`.
   - Derived values (mortgage rate, depreciation, risk drag) → computed once in
     `Model.__init__`.
   If a number appears in a label or prose string, interpolate it from the constant —
   do not retype it. (A literal "$250k" in HTML that should be `CG_EXCLUSION` will
   silently drift when the constant changes.)
   - This applies to *explanatory* figures too, not just the headline numbers. A
     reader-aid like "a dollar 20 yrs out is worth ~half today" is a claim derived from
     an assumption (`INFLATION_RATE`): add the constant to `assumptions.py`, compute the
     figure in `compute()` (e.g. `today_value_fraction = 1/(1+INFLATION_RATE)**hz`), and
     interpolate it — never assert "~3%" or "half" as prose. If you catch yourself typing
     a number into a sentence to make the report clearer, that number needs a source.

4. **Per-house vs. shared.** Before adding an input, decide: does it differ per house?
   → TOML + a `Property` field. Is it a market/tax/policy assumption reused across
   houses? → `assumptions.py`. When in doubt, if two houses in the same metro would
   share it, it's shared.

5. **Pin the analysis date.** `as_of_date` lives in the property TOML and is used for
   anything time-relative (e.g. `years_owned_as_residence`). Don't reintroduce
   `date.today()` — re-running months later must give identical numbers.

6. **`model.py` must be self-teaching.** This is financial/tax math where a wrong sign
   or a misunderstood rule is catastrophic and silent, so the code must explain *why*,
   not just *what* — to the standard that a competent newcomer (or a fresh Claude with
   no prior context from this project) could read `model.py` top-to-bottom and fully
   understand and defend every number, without needing a CPA or this chat history.
   Concretely, every calculation that encodes a financial/tax rule carries a comment
   that states:
   - **What real-world rule it implements** (e.g. "§121: gain attributable to
     non-qualified-use years is not excludable"), named so it can be looked up.
   - **Why it's done this way** — the reasoning or the choice between alternatives
     (e.g. "charged at the *after-tax* opportunity cost because the SELL path is taxed
     on its gains, so symmetry requires after-tax").
   - **Sign/unit conventions** where they matter (e.g. "outflows are negative";
     "annual nominal dollars"; "a rate in [0,1]").
   - **Known simplifications and their direction** (e.g. "flat effective rate; real
     brackets are graduated — slightly overstates tax in low-income years").
   When you add or change a formula, add/expand the comment so the *why* survives.
   Prefer a short prose comment over a clever one-liner. If a piece of logic can't be
   made clear in a comment, that's a signal to restructure it (extract a well-named
   pure function) until it can.

7. **Keep `render.py` in sync with `assumptions.py` / `model.py`.** render is a
   downstream consumer — when you add, rename, or remove an input or a `compute()` key,
   the report can silently go stale: a removed constant referenced in prose, an
   assumptions-table row that no longer reflects the inputs, or instructions that point
   at the wrong file (e.g. "edit `assumptions.py`" after a value moved to a TOML).
   - Surface every input that affects a number in the report's assumptions table, read
     from the `compute()` context dict — never retype a value render doesn't own.
   - When you change where an input lives or what it's called, grep `render.py` and
     `templates/` for the old name and any user-facing instructions about it.
   - The guard: after any input/model change, run `make report` and **read the output**
     — the assumptions table and term/mechanic explanations must still match the actual
     inputs (and must stay free of interpretation per rule 2). The golden snapshot guards
     the *numbers*; only your eyes guard the *words*.

8. **Density vs. fidelity: relocate, don't trade.** The report serves two reader
   questions, and a given element answers only one: *"What's going on?"* (the reader is
   forming a picture — the enemy is density) and *"Can I trust / defend this number?"*
   (the reader is verifying — the enemy is omission). Don't lower fidelity to gain
   clarity; move the fidelity to where the verifying reader looks for it. Apply this test
   to every sentence, row, and section, in order:
   1. **Does this detail change the reader's *picture* of the answer?** If yes → it
      belongs in the readable layer, stated plainly (e.g. "holding pays off only if the
      house beats ~4.3%/yr").
   2. **If it doesn't change the picture, does removing it make a stated number *wrong or
      unverifiable*?** If yes → keep it, but **demote** it to a footnote, the "how it's
      built" table, or the assumptions table — don't delete (e.g. "recapture carries NIIT
      and is capped at recognized gain" doesn't change the spouse's picture but you can't
      defend the recapture figure without it).
   3. **Neither?** → cut it. It's bloat. (This is the only blade against length; demoting
      everything downward keeps the report faithful but never shorter, so wield step 3
      deliberately.)
   The result is **progressive disclosure**: a readable picture-layer on top of a
   faithful verify-layer — not a style choice, just what the rule produces. For the rare
   element that genuinely *can't* be relocated (the only honest statement is itself hard,
   e.g. symmetric pre-tax-compound-then-tax-once), **state the faithful version, then
   append a one-clause plain gloss** ("…(in plain terms: …)") — the precise reader stops
   at the first clause, the layperson reads the gloss. You pay a few words, never
   accuracy. Still bound by rule 2: a plain gloss explains *mechanics*, never verdict.

## When you add a new input/knob

1. Add the field to the `Property` dataclass (`assumptions.py`) if per-house, else add
   a constant to `assumptions.py`.
2. If per-house, add it to **every** `properties/*.toml` (the loader uses `**data`, so
   a missing key raises `TypeError` — that's intentional, it forces you to set it).
3. Use it in `Model` via `self.p.<field>` (per-house) or the imported constant (shared).
4. If it should show in the report, add it to the assumptions table in `render.py` and
   surface it via the context dict — interpolated, never hardcoded.
5. Add/extend a test in `tests/test_model.py` if it affects the math.
6. Run `make check` (format-check + lint + tests) and `make report`; eyeball the output.
7. If the change moved any numbers **on purpose**, regenerate the golden snapshot
   (`make snapshot`) — see "Golden snapshots" below.

## When you add a new property

`cp properties/harold-ave.toml properties/<name>.toml`, edit values, then
`make report PROPERTY=properties/<name>.toml`. Two `Model` instances are independent
(no shared state) — there's a test for that.

## Workflow / commands

- `make check` — format-check + lint + tests. **Run before every commit** (the
  pre-commit hook runs it too; see below). Fix formatting with `make fmt`.
- `make report [PROPERTY=...]` — regenerate the HTML + text into `output/`.
- `make model [PROPERTY=...]` — dump `output/model_output.json` (audit artifact).
- `make snapshot` — regenerate the committed golden files (see below).
- **Pre-commit hook:** `scripts/pre-commit` runs `make check`. It's a plain git hook
  (no framework). Install once per clone:
  `ln -sf ../../scripts/pre-commit .git/hooks/pre-commit`.

## Commit cadence

Commit logical units as you build, not in one big batch at the end. When a coherent
piece is done and green (`make check` passes), commit it before starting the next —
e.g. a self-cleanup, a single bug fix, or one new feature is each its own commit. This
keeps each diff small and reviewable and ties every numeric change (and its golden-
snapshot update) to the one reason it moved. If a change moves numbers on purpose,
regenerate and commit the snapshot in the **same** commit. Don't bundle unrelated
fixes; don't wait until everything is done to make the first commit.

## Golden snapshots (the numeric safety net)

`tests/golden/*.json` are committed snapshots of `compute()` for each property.
`test_matches_golden_snapshot` diffs the live output against them (within $0.01), so
**any unintended change to a number fails a test** — the single most important guard
for a model whose whole value is stable, correct figures.

- **Refactoring (numbers shouldn't change):** do NOT run `make snapshot`. If the
  golden test fails, you changed a number you didn't mean to — investigate, don't
  regenerate.
- **Intentional change (a number SHOULD move):** verify the new numbers are right,
  then `make snapshot` to update the golden files, and commit them in the same change
  so the diff shows exactly what moved.
- The golden test is also why `scripts/snapshot.py` lists every property — add new
  ones there so they're covered.

## Tax modeling notes (where the subtlety lives)

- The hold path is taxed at the *future* sale: selling costs, depreciation recapture
  (fed 25% + CA ordinary), capital-gains on appreciation, and §121 treatment. The sell
  path's investment gains are also taxed at liquidation — keep these symmetric.
- Passive losses are **suspended** when MAGI is high and released at sale (no yearly
  shield). Don't "give back" the yearly depreciation shield unless
  `PASSIVE_LOSS_USABLE_YEARLY` is set.
- §121 has two treatments (`full_rental`, `within_3yr`). A "move back in to re-qualify"
  scenario is intentionally NOT modeled — it only earns the prorated exclusion if you
  also bear the offsetting cost (forgone rent + own housing over a longer timeline),
  which would more than cancel the benefit; modeling only the benefit overstates it.
- Depreciation recapture carries NIIT (`DEPREC_RECAPTURE_RATE` = fed 25% + NIIT 3.8% +
  CA 13.3%) and is capped at the recognized gain per §1250 (`tax_at_sale` takes the
  realized amount + cost basis to compute the cap). This is the area most worth a CPA's eyes.
- Property tax = assessed value × effective rate, grown at the 2% Prop 13 cap. It's
  stored as a flat dollar figure (assessed × rate) that grows — same result, simpler.
- Depreciable `building_basis` is per-property (TOML): lower-of-cost-or-FMV at
  conversion × a credible land/building split (use an appraisal, not a sandbagged
  county assessment). Precision is low-stakes — recapture ≈ suspended-loss release.
- Provenance for the tax rates and the §121/recapture/conversion rules:
  `docs/sf-rental-tax-reference.md` (cited SF/CA reference). When changing a tax rate,
  check it there first.

## Gotchas

- Run tests with `make check` (or `uv run python -m pytest`). Bare `pytest` may resolve
  to a system Python without `tomllib` (needs 3.11+).
- `output/` is generated and gitignored — never edit it by hand; edit inputs and re-run.
- `output/model_output.json` is an audit artifact (full computed dict), not an input to
  render. render calls `compute()` in-process.
- HTML is autoescaped (Jinja). Row HTML built in `render.py` is wrapped in `Markup` on
  purpose; user-facing strings like the address are escaped by default — keep it that way.
