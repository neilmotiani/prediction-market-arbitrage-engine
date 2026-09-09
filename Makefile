.PHONY: dev test backend frontend mock-data demo-report benchmark lint install
install:
	uv sync --frozen
	cd frontend && npm ci
dev:
	docker compose up --build
backend:
	PYTHONPATH=backend uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
frontend:
	cd frontend && npm run dev
mock-data:
	uv run python scripts/demo.py
demo-report:
	uv run python scripts/demo_report.py
benchmark:
	uv run python scripts/benchmark.py
lint:
	uv run ruff check backend tests scripts
	uv run ruff format --check backend tests scripts
	cd frontend && npm run lint && npm run typecheck && npm run format:check
test:
	uv run pytest --cov=app --cov-report=term-missing

.PHONY: live live-stop
live:
	docker compose -f docker-compose.yml -f docker-compose.live.yml up --build -d
live-stop:
	docker compose -f docker-compose.yml -f docker-compose.live.yml stop
