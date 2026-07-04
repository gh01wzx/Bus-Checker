import datetime
import sys
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator

PIPELINE_PATH = Path("/opt/airflow/bus-checker")


def collect_snapshot():
    if not PIPELINE_PATH.exists():
        raise ImportError(f"Pipeline path not found: {PIPELINE_PATH}")
    sys.path.insert(0, str(PIPELINE_PATH))
    import pipeline

    pipeline.run_pipeline()


default_args = {
    "retries": 2,
    "retry_delay": datetime.timedelta(seconds=60),
}

with DAG(
    dag_id="bus_pipeline",
    start_date=datetime.datetime(2025, 1, 1),
    schedule="*/5 * * * *",
    catchup=False,
    max_active_runs=1,
    tags=["bus"],
    default_args=default_args,
) as dag:
    collect_task = PythonOperator(
        task_id="collect_snapshot",
        python_callable=collect_snapshot,
    )
