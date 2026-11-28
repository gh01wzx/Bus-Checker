"""Housekeeping: retention of raw data, audit rows and archives, then vacuum/checkpoint."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from bus_checker.config import LOCAL_TZ, Settings
from bus_checker.realtime.archive import purge_archive
from bus_checker.schema import (
    DBT_RUNS,
    FETCH_RUNS,
    PUBLICATIONS,
    QUARANTINE,
    SERVICE_ALERT_ENTITIES,
    SERVICE_ALERTS,
    TRIP_UPDATES,
    VEHICLE_POSITIONS,
    ensure_ready,
)
from bus_checker.warehouse import open_warehouse, session

logger = logging.getLogger(__name__)
ALERT_RETENTION_DAYS = 180


def maintain(settings: Settings, now: datetime | None = None) -> dict[str, Any]:
    from zoneinfo import ZoneInfo

    now = now or datetime.now(UTC)
    today: date = now.astimezone(ZoneInfo(LOCAL_TZ)).date()
    report: dict[str, Any] = {}
    if settings.archive_dir is not None:
        report["archive_files_removed"] = purge_archive(settings.archive_dir, settings.archive_retention_days, now)

    ensure_ready(settings)
    with session(settings) as warehouse:
        if settings.raw_retention_days > 0:
            cutoff = today - timedelta(days=settings.raw_retention_days)
            for table in (TRIP_UPDATES, VEHICLE_POSITIONS):
                report[f"{table.name}_removed"] = warehouse.execute(
                    f"DELETE FROM {table.ref} WHERE service_date < :cutoff", {"cutoff": cutoff}
                )
        ops_cutoff = now - timedelta(days=settings.ops_retention_days)
        for table, column in (
            (FETCH_RUNS, "started_at"),
            (QUARANTINE, "created_at"),
            (DBT_RUNS, "started_at"),
            (PUBLICATIONS, "started_at"),
        ):
            report[f"{table.name}_removed"] = warehouse.execute(
                f"DELETE FROM {table.ref} WHERE {column} < :cutoff", {"cutoff": ops_cutoff}
            )
        alert_cutoff = now - timedelta(days=ALERT_RETENTION_DAYS)
        warehouse.execute(
            f"DELETE FROM {SERVICE_ALERT_ENTITIES.ref} WHERE alert_version_id IN ("
            f"SELECT alert_version_id FROM {SERVICE_ALERTS.ref} WHERE last_seen_at < :cutoff)",
            {"cutoff": alert_cutoff},
        )
        report["alert_versions_removed"] = warehouse.execute(
            f"DELETE FROM {SERVICE_ALERTS.ref} WHERE last_seen_at < :cutoff", {"cutoff": alert_cutoff}
        )

    warehouse = open_warehouse(settings, autocommit=True)
    try:
        if warehouse.kind == "postgres":
            for table in (TRIP_UPDATES, VEHICLE_POSITIONS, SERVICE_ALERTS, FETCH_RUNS, QUARANTINE):
                warehouse.execute(f"VACUUM (ANALYZE) {table.ref}")
            report["vacuum"] = "analyzed"
        else:
            warehouse.execute("CHECKPOINT")
            report["vacuum"] = "checkpointed"
    finally:
        warehouse.close()
    logger.info("Maintenance complete: %s", report)
    return report
