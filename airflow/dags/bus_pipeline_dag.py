import datetime
import sys
from airflow import DAG
from airflow.operators.python import PythonOperator

sys.path.insert(0, "/opt/airflow/bus-checker")


def run_pipeline():
    import pipeline

    pipeline.run_once()


with DAG(
    dag_id="bus_pipeline",
    start_date=datetime.datetime(2026, 1, 1),
    schedule="*/5 * * * *",
    catchup=False,
    max_active_runs=1,
    tags=["bus"],
) as dag:
    collect_task = PythonOperator(
        task_id="collect_snapshot", python_callable=run_pipeline
    )
