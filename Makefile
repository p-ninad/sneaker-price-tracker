.DEFAULT_GOAL := help

SERVICE ?= all

.PHONY: help install run dev dashboard ready test lint format clean docker-build docker-run docker-stop init db-reset db-migrate

help:
	@echo "Price Tracker Makefile"
	@echo "====================="
	@echo ""
	@echo "Commands:"
	@echo "  make install       - Install dependencies"
	@echo "  make init          - Initialize database"
	@echo "  make db-reset      - Drop and recreate database schema"
	@echo "  make run           - Run the application"
	@echo "  make dev           - Run in development mode with auto-reload"
	@echo "  make ready         - Run deploy-time readiness checks (SERVICE=all|dashboard|main|telegram-bot)"
	@echo "  make test          - Run tests"
	@echo "  make lint          - Run linter (ruff)"
	@echo "  make format        - Format code (black + ruff)"
	@echo "  make clean         - Clean build artifacts"
	@echo "  make docker-build  - Build Docker image"
	@echo "  make docker-run    - Start Docker container"
	@echo "  make docker-stop   - Stop Docker container"
	@echo "  make db-migrate    - Apply database migrations"
	@echo ""

install:
	pip install -r requirements.txt
	playwright install

init:
	export PYTHONPATH=./src && python3 -m app.database.bootstrap

db-reset:
	export PYTHONPATH=./src && python3 -m app.database.bootstrap --reset

run:
	export PYTHONPATH=./src && python3 -m app.main

dev:
	export PYTHONPATH=./src && python3 -m app.main

dashboard:
	export PYTHONPATH=./src && python3 -m app.dashboard

ready:
	export PYTHONPATH=./src && python3 -m app.readiness --service $(SERVICE)

test:
	export PYTHONPATH=./src && python3 -m pytest src/tests -v --cov=src/app

test-unit:
	export PYTHONPATH=./src && python3 -m pytest src/tests/unit -v

test-integration:
	export PYTHONPATH=./src && python3 -m pytest src/tests/integration -v

lint:
	ruff check src/app src/tests
	mypy src/app --ignore-missing-imports

format:
	black src/app src/tests
	ruff check --fix src/app src/tests

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	rm -rf build dist *.egg-info

docker-build:
	docker build -t price-tracker:latest .

docker-run:
	docker compose down --remove-orphans
	docker compose up -d --build

docker-stop:
	docker compose down

docker-logs:
	docker compose logs -f

docker-shell:
	docker compose exec price-tracker bash

# Development utilities
db-migrate:
	export PYTHONPATH=./src && python3 -m app.migrations upgrade head

db-seed:
	echo "Database seeding not yet implemented"

check:
	@echo "Running checks..."
	@ruff check src/app src/tests
	@black --check src/app src/tests
	@echo "✓ All checks passed"

# Quick setup
quickstart: install init
	@echo "✓ Environment ready. Run 'make run' to start."
