"""Bus Checker orchestration.

* ``bus_realtime``      every 5 min: collect feeds -> refresh GTFS when due -> dbt build -> publish
* ``bus_maintenance``   daily 04:15 NZ: retention, vacuum and a full-history data test run
* ``bus_publish_remote`` every 15 min (only when BUS_PUBLISH_URL is set): sync marts online

Every task shells out to the pipeline's own virtualenv (``python -m bus_checker``), so the
application's dependencies never conflict with Airflow's. Tasks that write the warehouse
share the ``bus_warehouse`` pool (one slot): DuckDB allows a single writer, and serialising
writes keeps PostgreSQL loads simple too.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG
from airflow.timetables.trigger import CronTriggerTimetable

CLI = os.environ.get("BUS_CLI", "/opt/bus-venv/bin/python -m bus_checker")
APP_DIR = os.environ.get("BUS_APP_DIR", "/opt/bus-checker")
BACKEND = os.environ.get("BUS_BACKEND", "postgres")
POOL = "bus_warehouse"
START = datetime(2026, 1, 1, tzinfo=UTC)
DEFAULTS = {
    "owner": "bus-checker",
    "retries": 1,
    "retry_delay": timedelta(seconds=30),
    "retry_exponential_backoff": False,
}


def command(task_id: str, args: str, **kwargs) -> BashOperator:
    return BashOperator(task_id=task_id, bash_command=f"{CLI} {args}", cwd=APP_DIR, **kwargs)


with DAG(
    dag_id="bus_realtime",
    description="Collect AT realtime feeds, transform with dbt and publish the dashboard data",
    schedule=CronTriggerTimetable("*/5 * * * *", timezone="UTC"),
    start_date=START,
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=20),
    default_args=DEFAULTS,
    tags=["bus-checker", "realtime"],
    doc_md=__doc__,
) as realtime:
    collect = command(
        "collect_realtime",
        'collect --run-id "{{ run_id }}"',
        pool=POOL,
        execution_timeout=timedelta(minutes=4),
    )
    reference = command(
        "refresh_gtfs_if_due",
        "gtfs --if-due",
        pool=POOL,
        trigger_rule="all_done",  # a collection failure must not block reference data
        execution_timeout=timedelta(minutes=10),
    )
    build = command(
        "build_and_test",
        "build",
        pool=POOL,
        trigger_rule="all_done",  # rebuild whatever was collected, even after a partial failure
        execution_timeout=timedelta(minutes=15),
    )
    collect >> reference >> build
    if BACKEND == "duckdb":
        publish = command(
            "publish_dashboard_snapshot",
            "publish-snapshot",
            pool=POOL,
            execution_timeout=timedelta(minutes=5),
        )
        build >> publish


with DAG(
    dag_id="bus_maintenance",
    description="Retention, vacuum and full-history data tests",
    schedule=CronTriggerTimetable("15 4 * * *", timezone="Pacific/Auckland"),
    start_date=START,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULTS,
    tags=["bus-checker", "maintenance"],
) as maintenance:
    maintain = command("apply_retention", "maintain", pool=POOL, execution_timeout=timedelta(minutes=30))
    full_tests = command("test_full_history", "build --full-tests", pool=POOL, execution_timeout=timedelta(minutes=60))
    maintain >> full_tests


if os.environ.get("BUS_PUBLISH_URL"):
    with DAG(
        dag_id="bus_publish_remote",
        description="Publish the dashboard marts to the hosted PostgreSQL database",
        schedule=CronTriggerTimetable(os.environ.get("BUS_PUBLISH_SCHEDULE", "*/15 * * * *"), timezone="UTC"),
        start_date=START,
        catchup=False,
        max_active_runs=1,
        default_args={**DEFAULTS, "retries": 2, "retry_delay": timedelta(minutes=2)},
        tags=["bus-checker", "publish"],
    ) as publish_remote:
        # Reads the published DuckDB snapshot (or PostgreSQL marts), so it needs no pool slot.
        command("sync_remote", "sync-remote", execution_timeout=timedelta(minutes=20))
