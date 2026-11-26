# Bus Checker

Bus Checker follows Auckland Transport delay predictions from the realtime API to six local Streamlit pages. Airflow schedules ingestion every five minutes. Choose **PostgreSQL** or **DuckDB** when starting Docker Compose. Both use the same parser, dbt models, data tests and dashboard.

## Run locally

Install Docker Desktop with Linux containers and run the following from the repository root in PowerShell. On first use, create `.env` with `Copy-Item .env.example .env` if it does not already exist. Set `AT_SUB_KEY` to your Auckland Transport subscription key. The Docker default warehouse is PostgreSQL.

```powershell
$env:BUS_BACKEND = "postgres"   # or "duckdb"
docker compose up --build -d
docker compose ps
```

Open [Airflow](http://localhost:8080) and [Streamlit](http://localhost:8501). The Airflow user is `admin`. Retrieve the locally generated password with `docker compose exec airflow cat /opt/airflow/state/passwords.json`. The `bus_pipeline` DAG starts enabled. On first collection it downloads the public GTFS reference feed. The dashboard fills after the first successful build.

For a permanent backend selection set `BUS_BACKEND` in the root `.env`. A shell setting overrides the file. Switch after the current DAG run finishes with `docker compose down`, then select the other backend and start again. Each warehouse keeps its own history in its Docker volume. Switching back resumes that warehouse. The old native `bus_data.duckdb` file and earlier Compose volumes are separate. Keep those when migrating. Stop the previous Airflow project before starting this one if it holds port 8080. Keep the PC awake and Docker running for continuous coverage. Missed live predictions cannot be reconstructed from the current feed.

## What happens to each snapshot

1. **Collect.** The collector fetches AT trip updates, archives the raw JSON and records source time, ingestion time and run status. Deterministic batch and observation IDs allow replay. Rejected records retain their reason. A transaction commits accepted observations, quarantine and the successful run record together.
2. **Refresh reference data.** A successful GTFS refresh is valid for seven days. Empty tables and invalid route or stop keys are rejected before replacement. The timestamp and the three replacement tables commit together. Collection runs first, so a reference download failure still leaves the realtime batch available.
3. **Build and test.** dbt builds staging, trip facts, hourly route reliability and daily stop reliability. Tests check grain, counts, allowed values and reconciliation against raw observations. Airflow retries failed tasks twice. A subsequent run can model a previously collected batch.
4. **Serve.** Streamlit shows network trends, route comparisons, stop hotspots, route reliability, historical summaries and ingestion health. An on-time prediction falls between 60 seconds early and 300 seconds late, inclusive. Metrics count samples. The same journey may contribute several observations.

| Local backend | Storage and dashboard reads |
| --- | --- |
| PostgreSQL | One local server hosts separate Airflow and bus databases with separate owners. The dashboard uses a read-only role. Models become visible as dbt commits them. |
| DuckDB | Airflow is the single writer. After a passing dbt build it checkpoints the file and atomically replaces a separate dashboard snapshot on the same filesystem. A failed build leaves the previous published snapshot available. The health page then reflects the last publication. Snapshot copy time and disk use grow with warehouse size. |

Docker publishes only the Airflow and dashboard ports on loopback. PostgreSQL stays inside the Compose network. The API key is passed only to Airflow. The checked-in passwords are local demo defaults. Set the three database role passwords and bootstrap password before first initialization to use your own. Use URL-safe characters for the Airflow database password. Changing an environment variable alone does not rotate an existing PostgreSQL role password.

## Operation and validation

| Command from repository root | Purpose |
| --- | --- |
| `docker compose logs -f airflow` | Watch scheduler startup and find the Airflow UI |
| `docker compose exec airflow airflow dags trigger bus_pipeline` | Request another pipeline run |
| `docker compose down` | Stop containers and keep named volumes |
| `docker compose config -q` | Validate the configuration without printing secrets |
| `make test` | Run Python unit tests in the native Python 3.11 environment |
| `.\.venv\Scripts\python.exe tests/check_warehouse.py` | Exercise initial and incremental builds, replay, late data and all six pages in a temporary DuckDB warehouse |

The GitHub quality workflow runs deterministic local HTTP fixtures on isolated runners for both Docker backend selections. The scheduler executes the DAG, then the checks read the resulting metrics and open the dashboard pages. Scheduled live collection belongs to the local machine. CI uses fixture credentials.

For native development, run `make setup`, select `BUS_BACKEND=duckdb`, then use `make load-gtfs`, `make collect`, `make dbt-run` and `make dashboard`. Native DuckDB defaults to the repository's `bus_data.duckdb`. An existing native PostgreSQL installation can be configured using `BUS_POSTGRES_URL` or standard `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER` and `PGPASSWORD`. The Docker warehouse and host development setup have independent storage.

## Planned publication to Supabase

The next phase is a separate Airflow publication task after a successful dbt build. Publish the aggregates and historical partitions needed by the online dashboard. For late arrivals, replace every affected date partition in a transaction. Record the publication ID, source batches, counts and completion time, verify the destination totals and advance the checkpoint only after commit. An online Streamlit app can read the last complete publication with a read-only account while the local collector continues independently. This is a design for a future phase.

Auckland Transport bus data is licensed under CC BY 4.0. [AT developer portal](https://dev-portal.at.govt.nz/).
