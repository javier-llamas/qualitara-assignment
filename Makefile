.PHONY: setup fmt lint type check test test-backend test-frontend up down migrate simulate clean

setup:
	cd backend && uv sync
	cd frontend && npm install

fmt:
	cd backend && uv run ruff format
	cd frontend && npx prettier --write "src/**/*.{ts,tsx}" 2>/dev/null || true

lint:
	cd backend && uv run ruff check --fix
	cd backend && uv run ruff format
	cd frontend && npm run lint -- --fix || true

type:
	cd backend && uv run mypy app
	cd frontend && npm run typecheck

isort:
	cd backend && uv run isort .

# Aggregate gate — runs ruff + mypy. Wired into the Claude Code Stop hook.
check: lint type isort

test-backend:
	cd backend && uv run pytest

test-frontend:
	cd frontend && npx jest

test: test-backend test-frontend

up:
	docker compose up --build -d

down:
	docker compose down

migrate:
	docker compose run --rm migrate

simulate:
	cd backend && uv run python -m scripts.simulate --url http://localhost:8080/api

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	cd backend && rm -rf .ruff_cache .mypy_cache
	cd frontend && rm -rf node_modules dist coverage
