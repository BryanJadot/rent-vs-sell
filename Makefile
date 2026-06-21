.PHONY: report model check snapshot fmt clean
# Per-property inputs; override with: make report PROPERTY=properties/other.toml
PROPERTY ?= properties/harold-ave.toml

# Generate the HTML reports + text summary into output/
report:
	uv run python render.py $(PROPERTY)

# Recompute the model and dump output/model_output.json (audit artifact)
model:
	uv run python model.py $(PROPERTY)

# Pre-flight: format-check + lint + tests. Run before committing.
# (format --check fails if unformatted; run `make fmt` to fix.)
check:
	uv run ruff format --check .
	uv run ruff check .
	uv run python -m pytest -q

# Regenerate the committed golden snapshots. Run DELIBERATELY, only after you've
# verified a numeric change is intended — it rewrites what the tests diff against.
snapshot:
	uv run python scripts/snapshot.py

fmt:
	uv run ruff format .

clean:
	rm -rf output __pycache__ .pytest_cache .ruff_cache
