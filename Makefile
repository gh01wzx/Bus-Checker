SYSTEM_PYTHON ?= python

ifeq ($(OS),Windows_NT)
PYTHON := .venv/Scripts/python.exe
else
PYTHON := .venv/bin/python
endif

.PHONY: setup collect load-gtfs dbt-run dbt-test test dbt-docs dashboard airflow-up airflow-down

setup:
	$(SYSTEM_PYTHON) -m venv .venv
	$(PYTHON) -m pip install -r requirements.txt

collect:
	$(PYTHON) pipeline.py collect

load-gtfs:
	$(PYTHON) pipeline.py load-gtfs

dbt-run:
	$(PYTHON) pipeline.py build

dbt-test: dbt-run

test:
	$(PYTHON) -m unittest discover -s tests -v

dbt-docs:
	$(PYTHON) pipeline.py build --docs

dashboard:
	$(PYTHON) -m streamlit run dashboard.py --server.address 127.0.0.1

airflow-up:
	cd airflow && docker compose up -d

airflow-down:
	cd airflow && docker compose down