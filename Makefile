PYTHON ?= .venv/bin/python
RUFF ?= .venv/bin/ruff

.PHONY: check lint format test build

check: lint test

lint:
	$(RUFF) check .
	$(RUFF) format --check .

format:
	$(RUFF) format .

test:
	$(PYTHON) -m unittest discover -s tests -v

build:
	$(PYTHON) -m pip wheel --no-deps --wheel-dir dist .
