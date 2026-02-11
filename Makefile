.PHONY: help install install-dev lint format typecheck test test-cov clean

PYTHON ?= python3

help:
	@echo "Available targets:"
	@echo "  install      Install the package"
	@echo "  install-dev  Install with development dependencies"
	@echo "  lint         Run linter (ruff check)"
	@echo "  format       Format code (ruff format)"
	@echo "  typecheck    Run type checker (mypy)"
	@echo "  test         Run tests"
	@echo "  test-cov     Run tests with coverage report"
	@echo "  clean        Remove build artifacts"

install:
	$(PYTHON) -m pip install .

install-dev:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(PYTHON) -m ruff check gl_settings.py tests/

format:
	$(PYTHON) -m ruff format gl_settings.py tests/
	$(PYTHON) -m ruff check --fix gl_settings.py tests/

typecheck:
	$(PYTHON) -m mypy gl_settings.py

test:
	$(PYTHON) -m pytest tests/ -v

test-cov:
	$(PYTHON) -m pytest tests/ -v --cov=gl_settings --cov-report=term-missing --cov-report=html

clean:
	rm -rf build/ dist/ *.egg-info/ .pytest_cache/ .ruff_cache/ .mypy_cache/ htmlcov/ .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
