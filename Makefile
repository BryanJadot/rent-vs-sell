.PHONY: report model test lint fmt clean
# Per-property inputs; override with: make report PROPERTY=properties/other.toml
PROPERTY ?= properties/harold-ave.toml

# Generate the HTML reports + text summary into output/
report:
	uv run python render.py $(PROPERTY)

# Just recompute the model and dump output/model_output.json
model:
	uv run python model.py $(PROPERTY)

test:
	uv run python -m pytest -q

lint:
	uv run ruff check .

fmt:
	uv run ruff format .

clean:
	rm -rf output __pycache__ .pytest_cache .ruff_cache
