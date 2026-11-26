import os
from datetime import datetime, timedelta, timezone

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

PIPELINE = "/opt/airflow/bus-venv/bin/python /opt/airflow/bus-checker/pipeline.py"

with DAG(
    dag_id="bus_pipeline",
    start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
    schedule="*/5 * * * *",
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=1),
                  "execution_timeout": timedelta(minutes=25)},
    tags=["auckland", "local"],
) as dag:
    collect = BashOperator(task_id="collect_snapshot", bash_command=f"{PIPELINE} collect")
    reference = BashOperator(
        task_id="refresh_reference_if_due", bash_command=f"{PIPELINE} load-gtfs --if-stale"
    )
    transform = BashOperator(
        task_id="build_and_test_analytics", bash_command=f"{PIPELINE} build"
    )
    collect >> reference >> transform
    if os.environ.get("BUS_BACKEND", "postgres") == "duckdb":
        publish = BashOperator(
            task_id="publish_dashboard_snapshot", bash_command=f"{PIPELINE} publish-snapshot"
        )
        transform >> publish
