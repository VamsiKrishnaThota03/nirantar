.PHONY: help setup backend frontend dev build test lint shots docker clean

PY := backend/.venv/bin/python
PIP := backend/.venv/bin/pip

help:
	@echo "Nirantar — continuity of care for a billion"
	@echo ""
	@echo "  make setup     install backend and frontend dependencies"
	@echo "  make build     build the dashboard (served by the backend)"
	@echo "  make backend   run the API on 127.0.0.1:8000"
	@echo "  make frontend  run the Vite dev server on 127.0.0.1:5173"
	@echo "  make test      run the backend suite and the frontend typecheck"
	@echo "  make shots     capture dashboard screenshots into docs/screenshots"
	@echo "  make docker    build and run the container (published to loopback)"
	@echo ""
	@echo "Set ANTHROPIC_API_KEY to enable the reasoning agents."
	@echo "Everything works without it; see README.md."

setup:
	python3 -m venv backend/.venv
	$(PIP) install --upgrade pip
	$(PIP) install -r backend/requirements.txt
	cd frontend && npm install

build:
	cd frontend && npm run build

# Loopback bind. HOST is overridden only by a container platform's own config.
backend:
	cd backend && HOST=127.0.0.1 PORT=8000 \
		DB_PATH=./var/nirantar.sqlite3 \
		LEDGER_KEY_PATH=./var/ledger_signing_key.pem \
		./.venv/bin/python -m uvicorn nirantar.main:app \
			--host 127.0.0.1 --port 8000 --reload

frontend:
	cd frontend && npm run dev

dev: build backend

test:
	cd backend && ./.venv/bin/python -m pytest tests -q
	cd frontend && npm run build

shots:
	cd frontend && npm run shots -- ../docs/screenshots

docker:
	docker compose up --build

clean:
	rm -rf backend/var backend/.pytest_cache frontend/dist
	find backend -name '__pycache__' -type d -prune -exec rm -rf {} +
