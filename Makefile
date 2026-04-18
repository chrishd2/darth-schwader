PYTHON ?= python3.12
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: install dev lint typecheck test test-cov migrate migrate-gen oauth clean

install:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"

dev:
	$(BIN)/uvicorn darth_schwader.main:create_app --factory --reload --host 127.0.0.1 --port 8000

lint:
	$(BIN)/ruff check src scripts

typecheck:
	$(BIN)/mypy src scripts

test:
	$(BIN)/pytest

test-cov:
	$(BIN)/pytest --cov=src --cov-report=term-missing

migrate:
	DATABASE_URL=$${DATABASE_URL:-sqlite+aiosqlite:///./data/darth_schwader.db} $(BIN)/alembic upgrade head

migrate-gen:
	DATABASE_URL=$${DATABASE_URL:-sqlite+aiosqlite:///./data/darth_schwader.db} \
	$(BIN)/alembic revision --autogenerate -m "$(message)"

oauth:
	$(BIN)/python scripts/schwab_oauth_login.py

clean:
	rm -rf $(VENV)
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
