.PHONY: up down migrate seed run test lint format check

up:
	docker compose up -d

down:
	docker compose down -v

migrate:
	alembic upgrade head

seed:
	PYTHONPATH=. python3 scripts/seed.py --name "Acme Corp" --plan free

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	pytest -q

lint:
	ruff check app tests
	mypy app tests

format:
	ruff format app tests
	black app tests

check: lint test
