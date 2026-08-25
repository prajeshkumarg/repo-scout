.PHONY: help deps dev test lint eval install clean

BACKEND := backend
WEB := web

# The API binds all interfaces so `make dev` also works when the app is
# opened from a phone or another machine on the same network; the web
# dev server already does. Override to lock it to this machine:
#   make dev API_HOST=127.0.0.1
API_HOST ?= 0.0.0.0

help:
	@echo "make dev    starts api, worker, and web"
	@echo "make test   pytest"
	@echo "make eval   runs the eval suite against the fixture repos"
	@echo "make lint   ruff + tsc"

install:
	cd $(BACKEND) && uv sync
	cd $(WEB) && npm install

# Postgres and redis only. The app runs on the host.
deps:
	docker compose up -d --wait

# `uv run` syncs the backend venv on demand; npm does not, so make it explicit.
# This is what lets `make dev` work from a clean clone.
$(WEB)/node_modules: $(WEB)/package.json $(WEB)/package-lock.json
	cd $(WEB) && npm install
	@touch $(WEB)/node_modules

dev: deps $(WEB)/node_modules
	@echo "api  http://127.0.0.1:8000  (bound to $(API_HOST))"
	@echo "web  http://localhost:3000"
	@# set -m puts each background job in its own process group, so the trap
	@# can kill a whole tree (uv spawns python as a child) with kill -- -PGID.
	@set -m; \
	trap 'kill -- -$$API -$$WORKER -$$WEB 2>/dev/null' EXIT INT TERM; \
	( cd $(BACKEND) && uv run uvicorn api.main:app --reload --host $(API_HOST) --port 8000 ) & API=$$!; \
	( cd $(BACKEND) && uv run python -m worker.main ) & WORKER=$$!; \
	( cd $(WEB) && npm run dev ) & WEB=$$!; \
	wait

test:
	cd $(BACKEND) && uv run pytest

lint:
	cd $(BACKEND) && uv run ruff check .
	cd $(BACKEND) && uv run ruff format --check .
	cd $(WEB) && npx tsc --noEmit

# The eval suite is not a unit test: it indexes fixture repos and runs 60
# retrievals. Baseline comparison happens via --check-regression in CI.
eval:
	cd $(BACKEND) && uv run python ../evals/run.py

clean:
	docker compose down
