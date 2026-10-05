# Bus Checker

Auckland bus reliability dashboard using Python, SQL, dbt and Streamlit, with DuckDB locally or Postgres. Six pages cover network trends, route comparisons, stop hotspots, route reliability, historical summaries and data health.

## Run locally

Python 3.11, PowerShell, from the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-engineering.txt
$env:BUS_BACKEND = 'duckdb'
.\Start-Local.ps1
```

With an existing populated database, the dashboard is ready to use. For a new database, set `AT_SUB_KEY` in `.env` and run these before opening it:

```powershell
.\.venv\Scripts\python.exe pipeline.py load-gtfs
.\.venv\Scripts\python.exe pipeline.py collect
.\.venv\Scripts\python.exe pipeline.py build
```

To refresh data, rerun `pipeline.py collect` and `pipeline.py build`. To migrate existing trip history, run `pipeline.py import-history` before the build. Finish DuckDB writes before opening or refreshing the dashboard.

If PowerShell blocks the launcher, use `.\.venv\Scripts\python.exe -m streamlit run dashboard.py --server.address 127.0.0.1`.

## Configuration

- `BUS_BACKEND`: `duckdb` for local use, or `postgres`.
- `BUS_DUCKDB_PATH`: optional; defaults to `bus_data.duckdb`.
- `AT_SUB_KEY`: required for live collection.
- `SUPABASE_DB_URL`: required for Postgres. Keep credentials in `.env`.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tests/check_warehouse.py
```

The integration check uses a temporary database without API credentials. `dashboard.py` opens the dashboard; `pipeline.py` runs data commands. Internal Python code lives in `bus_checker/`, pages in `bus_checker/ui/`, and SQL models in `bus_dbt/`. Run `python pipeline.py --help` for all data commands.

Metrics count reported bus delay observations, not completed journeys. On time means −60 to +300 seconds; dates use Auckland time. Local use requires no paid service. Cloud and scheduler execution have not been verified locally.

Bus data © Auckland Transport, licensed under CC BY 4.0.
