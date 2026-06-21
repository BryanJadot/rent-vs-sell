# Rent vs. Sell

A small financial model that compares two choices for a house you own:

- **SELL** it now and invest the after-tax proceeds, vs.
- **RENT** it out, hold, and sell later.

It produces an HTML report and a plain-text summary — **data only**: figures,
sensitivities, and explanations of how each number is built. It deliberately contains
**no interpretation** (no verdict or recommendation); interpretation is meant to be
produced by a separate downstream prompt so it isn't anchored by baked-in conclusions.
The comparison is apples-to-apples: the hold path is charged the costs **and** taxes of
the eventual future sale, and its cash flow is carried forward the same way the invested
sale proceeds are (grown pre-tax, gain taxed once at the end).

> Estimates only. Confirm the tax treatment with a CPA and the rent/risk figures with a
> property manager before making a decision.

## Quick start

```sh
uv sync                 # create the venv from pyproject/uv.lock
make report             # build output/ for the default property
open output/report.html
```

Or target a specific property:

```sh
make report PROPERTY=properties/harold-ave.toml
# equivalently:
uv run python render.py properties/harold-ave.toml
```

Other targets: `make check` (format-check + lint + tests, run before committing),
`make model` (dump `output/model_output.json` audit artifact), `make snapshot`
(regenerate golden files after an intended numeric change), `make fmt`, `make clean`.

## Analyzing a different house

Copy a property file and edit the values — nothing else needs to change:

```sh
cp properties/harold-ave.toml properties/my-house.toml
$EDITOR properties/my-house.toml
make report PROPERTY=properties/my-house.toml
```

The per-property TOML holds the house's value, basis, loan, taxes, rent comps,
reserve, and the pinned analysis date. Shared market/tax assumptions (SF appreciation,
rent growth, tax rates, risk probabilities) live in `assumptions.py`.

## Layout

| Path | Role |
|---|---|
| `properties/*.toml` | per-house inputs (one file per property) |
| `assumptions.py` | shared market/tax/policy assumptions + the `Property` loader |
| `model.py` | `Model` class — all financial math; `compute()` returns a dict |
| `render.py` | presentation — builds the HTML/text from the model |
| `templates/` | Jinja2 templates for the two HTML pages |
| `tests/` | pytest suite locking the math invariants |
| `output/` | generated artifacts (gitignored) |

Dependency direction is one-way: `render → model → assumptions`.

See `CLAUDE.md` for the design rules and what to watch when changing things.
