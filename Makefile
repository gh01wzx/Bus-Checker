# Native development helpers. On Windows without make, run the commands shown in README.md.
SYSTEM_PYTHON ?= python
ifeq ($(OS),Windows_NT)
PYTHON := .venv/Scripts/python.exe
else
PYTHON := .venv/bin/python
endif
CLI := $(PYTHON) -m bus_checker

.PHONY: setup init collect gtfs build publish run-once sync maintain status dashboard \
        test test-fast lint format docs up down logs stack-test

setup:            ## Create the virtualenv with development dependencies
	$(SYSTEM_PYTHON) -m venv .venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements-dev.txt

init:             ## Create warehouse schemas and tables
	$(CLI) init

collect:          ## Fetch and load the three AT realtime feeds once
	$(CLI) collect

gtfs:             ## Refresh GTFS reference data (when due)
	$(CLI) gtfs --if-due

build:            ## dbt build: models and data tests
	$(CLI) build

publish:          ## Publish the DuckDB dashboard snapshot
	$(CLI) publish-snapshot

run-once:         ## collect + gtfs (if due) + build + publish
	$(CLI) run-once

sync:             ## Publish the marts to BUS_PUBLISH_URL (Supabase)
	$(CLI) sync-remote

maintain:         ## Retention and vacuum
	$(CLI) maintain

status:
	$(CLI) status

dashboard:        ## Streamlit on http://127.0.0.1:8501
	$(PYTHON) -m streamlit run streamlit_app.py --server.address 127.0.0.1

test:             ## All tests (PostgreSQL tests need BUS_TEST_POSTGRES_URL)
	$(PYTHON) -m pytest -q

test-fast:        ## Unit tests only
	$(PYTHON) -m pytest -q tests/unit

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

docs:             ## dbt docs (bus_dbt/target/index.html)
	$(CLI) docs

up:               ## Start the Docker stack (BUS_BACKEND=postgres|duckdb)
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f airflow-scheduler

stack-test:       ## Full Docker end-to-end test against fixture feeds
	bash tests/stack/run_stack.sh
