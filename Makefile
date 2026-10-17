.PHONY: help install dev test lint format run docker-up docker-down clean

help:
	@echo "TELRO — available targets:"
	@echo "  make install     create .venv and install runtime dependencies"
	@echo "  make dev         install runtime + dev dependencies"
	@echo "  make run         start the bot (polling)"
	@echo "  make test        run the test suite"
	@echo "  make lint        ruff check"
	@echo "  make format      ruff format + import sort"
	@echo "  make docker-up   docker compose up -d --build"
	@echo "  make docker-down docker compose down"
	@echo "  make clean       remove caches"

install:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.txt

dev: install
	.venv/bin/pip install -r requirements-dev.txt

run:
	.venv/bin/python -m bot

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check bot tests

format:
	.venv/bin/ruff check --fix bot tests
	.venv/bin/ruff format bot tests

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__ bot/__pycache__
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
