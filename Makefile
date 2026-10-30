SRC := src/devdust
PY  ?= python3

.PHONY: help install test cov lint format demo fix clean

help:  ## Show this help
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install:  ## Editable install with dev extras
	$(PY) -m pip install -e ".[dev]"

test:  ## Run the test suite
	$(PY) -m pytest

cov:  ## Run the tests with a coverage report
	$(PY) -m pytest --cov --cov-report=term-missing

lint:  ## Check formatting and lint rules
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format:  ## Format the code
	$(PY) -m ruff format .

fix:  ## Apply every safe lint fix
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

demo:  ## Regenerate docs/demo.svg and docs/demo-delete.svg from real output
	PYTHONPATH=$(SRC) COLUMNS=100 $(PY) scripts/render_demo.py

clean:  ## Remove caches and build output
	rm -rf build dist .pytest_cache .ruff_cache .coverage htmlcov *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
