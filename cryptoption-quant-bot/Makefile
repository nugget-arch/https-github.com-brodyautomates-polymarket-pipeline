.PHONY: help install up down migrate dev-api dev-web test test-api test-web lint fmt build compose-check

help:
	@echo "install  up  down  migrate  dev-api  dev-web  test  lint  build  compose-check"

install:
	cd apps/api && pip install -e ".[dev]"
	cd packages/quant_engine && pip install -e .
	cd apps/web && npm install

up:
	docker compose up -d --build

down:
	docker compose down

compose-check:
	docker compose config >/dev/null && echo "compose OK"

migrate:
	cd apps/api && alembic upgrade head

dev-api:
	cd apps/api && uvicorn cryptoption_api.main:app --reload --port 8000

dev-web:
	cd apps/web && npm run dev

test: test-api test-web

test-api:
	cd apps/api && pytest -q

test-web:
	cd apps/web && npm run test -- --run

lint:
	cd apps/api && ruff check . && mypy cryptoption_api
	cd apps/web && npm run typecheck

fmt:
	cd apps/api && ruff format . && ruff check --fix .

build:
	cd apps/web && npm run build
