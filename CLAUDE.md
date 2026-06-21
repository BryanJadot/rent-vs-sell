# CLAUDE.md — working notes for this project

Guidance for making changes here without breaking the design. Read this before editing.

## What this is

A rent-vs-sell financial model for a house. It computes whether selling now and
investing beats renting it out and selling later, on an apples-to-apples after-tax
basis, and renders an HTML report + interpretation page + text summary.

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
   it belongs in `model.py`. render only formats and arranges. The verdict *prose* is
   assembled in render, but every *number* and every beats/trails/ties decision comes
   from `model.compute()` — so the words can never contradict the tables.

2. **No magic numbers / no duplicated values.** Every rate, threshold, or input has
   exactly one definition:
   - Per-house values → the property's TOML (`properties/*.toml`).
   - Shared market/tax/policy values → `assumptions.py`.
   - Derived values (mortgage rate, depreciation, risk drag) → computed once in
     `Model.__init__`.
   If a number appears in a label or prose string, interpolate it from the constant —
   do not retype it. (A literal "$250k" in HTML that should be `CG_EXCLUSION` will
   silently drift when the constant changes.)

3. **Per-house vs. shared.** Before adding an input, decide: does it differ per house?
   → TOML + a `Property` field. Is it a market/tax/policy assumption reused across
   houses? → `assumptions.py`. When in doubt, if two houses in the same metro would
   share it, it's shared.

4. **Pin the analysis date.** `as_of_date` lives in the property TOML and is used for
   anything time-relative (e.g. `years_owned_as_residence`). Don't reintroduce
   `date.today()` — re-running months later must give identical numbers.

## When you add a new input/knob

1. Add the field to the `Property` dataclass (`assumptions.py`) if per-house, else add
   a constant to `assumptions.py`.
2. If per-house, add it to **every** `properties/*.toml` (the loader uses `**data`, so
   a missing key raises `TypeError` — that's intentional, it forces you to set it).
3. Use it in `Model` via `self.p.<field>` (per-house) or the imported constant (shared).
4. If it should show in the report, add it to the assumptions table in `render.py` and
   surface it via the context dict — interpolated, never hardcoded.
5. Add/extend a test in `tests/test_model.py` if it affects the math.
6. Run `make test && make lint && make report` and eyeball the output.

## When you add a new property

`cp properties/harold-ave.toml properties/<name>.toml`, edit values, then
`make report PROPERTY=properties/<name>.toml`. Two `Model` instances are independent
(no shared state) — there's a test for that.

## Tax modeling notes (where the subtlety lives)

- The hold path is taxed at the *future* sale: selling costs, depreciation recapture
  (fed 25% + CA ordinary), capital-gains on appreciation, and §121 treatment. The sell
  path's investment gains are also taxed at liquidation — keep these symmetric.
- Passive losses are **suspended** when MAGI is high and released at sale (no yearly
  shield). Don't "give back" the yearly depreciation shield unless
  `PASSIVE_LOSS_USABLE_YEARLY` is set.
- §121 has three treatments (`full_rental`, `within_3yr`, `move_back`) — the proration
  is an approximation flagged as such. This is the area most worth a CPA's eyes.
- Property tax = assessed value × effective rate, grown at the 2% Prop 13 cap. It's
  stored as a flat dollar figure (assessed × rate) that grows — same result, simpler.

## Gotchas

- Run tests with `uv run python -m pytest` (or `make test`). Bare `pytest` may resolve
  to a system Python without `tomllib` (needs 3.11+).
- `output/` is generated and gitignored — never edit it by hand; edit inputs and re-run.
- `output/model_output.json` is an audit artifact (full computed dict), not an input to
  render. render calls `compute()` in-process.
- HTML is autoescaped (Jinja). Row HTML built in `render.py` is wrapped in `Markup` on
  purpose; user-facing strings like the address are escaped by default — keep it that way.
