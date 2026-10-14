# Bus Checker

Auckland bus reliability dashboard built with Python, dbt and Streamlit. Six pages explore network trends, route comparisons, stop hotspots, route reliability, historical summaries and data health.

## First-time setup

Requires Python 3.11 and GNU Make. Docker is optional for some functionalities, but it is required if you wish to run Airflow locally to collect data into your local db.
Run all commands from the project directory.
The Makefile uses `.venv` directly, so activation is unnecessary.

### Set up
This step uses Python to install all necessary dependencies listed in [requirements.txt](requirements.txt).

```powershell
cd Bus-Checker
make setup
```

If your Python command is `python3`, use `make setup SYSTEM_PYTHON=python3`.

Create a `.env` file in the project directory and set up your local db and `AT_SUB_KEY`.

```dotenv
AT_SUB_KEY=your_subscription_key
BUS_BACKEND=duckdb  # You can copy this; DuckDB is installed if you have run "make setup".
```

Use your Auckland Transport API subscription key (free to get from [here](https://dev-portal.at.govt.nz/)).

Prepare the data, then start the dashboard:

```powershell
make load-gtfs   # required at least once
make collect     # make one collection
make dbt-run     # dbt builds the models
make dashboard   # see the results
```

Open the local URL printed by Streamlit. These steps download route and stop reference data, collect delay observations, build statistics, and launch the dashboard.


## Commands

| Command | Purpose |
| --- | --- |
| `make setup` | Create `.venv` and install dependencies |
| `make load-gtfs` | Refresh route and stop reference data |
| `make collect` | Collect one realtime snapshot |
| `make dbt-run` | Build analytics and run data tests |
| `make dbt-test` | Alias for `make dbt-run` |
| `make dbt-docs` | Generate dbt documentation |
| `make test` | Run Python unit tests |
| `make dashboard` | Start the dashboard on this computer |
| `make airflow-up` / `make airflow-down` | Start / stop the optional Docker services |

## Optional scheduling

Docker Compose runs Airflow and its supporting services. Configure `airflow/.env` for `airflow/docker-compose.yaml` before running `make airflow-up`. Open Airflow at `http://localhost:8080` and enable `bus_pipeline`, which is paused when first created.

The DAG collects data every five minutes, then builds and tests analytics. The dashboard starts separately. For continuous collection alongside the dashboard, use Postgres to avoid DuckDB file access conflicts. The Postgres service in Compose stores Airflow metadata; it is not automatically the bus data database. Docker and cloud scheduling have not been verified locally.

## Configuration

Keep configuration and credentials in `.env`:

- `AT_SUB_KEY`: required for realtime collection.
- `BUS_BACKEND`: `duckdb` for local use or `postgres`.
- `BUS_DUCKDB_PATH`: optional local database path; defaults to `bus_data.duckdb`.
- `SUPABASE_DB_URL`: required for the Postgres backend.

## Project and tests

`pipeline.py` provides data commands; `bus_checker/` contains Python logic and dashboard pages; `bus_dbt/` contains SQL models and data tests. `dashboard.py` is the dashboard entry point.

Run `make test` for unit tests. On Windows, run the integration check with:

```powershell
.\.venv\Scripts\python.exe tests/check_warehouse.py
```

On macOS/Linux, use `.venv/bin/python` instead. The integration check uses a temporary database without API credentials. To import existing trip history, run the virtual environment's Python with `pipeline.py import-history` before building analytics.

Metrics count reported delay predictions, not completed journeys. On time means -60 to +300 seconds inclusive; dates and hours use Auckland time.

Bus data: Auckland Transport, licensed under CC BY 4.0.
