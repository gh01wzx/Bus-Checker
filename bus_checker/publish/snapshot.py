"""Publish a read-only DuckDB file holding only the dashboard marts.

DuckDB allows a single writer. Rather than let the dashboard open the warehouse (and block
the collector), every successful build publishes a compact snapshot of the ``marts``
schema to a separate file that is swapped in atomically. Readers see either the previous
or the new publication, never a partial one, and the copy stays small because raw data is
not included.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bus_checker.config import Settings
from bus_checker.ids import new_uuid
from bus_checker.publish.contract import MARTS, MARTS_SCHEMA, PUBLICATION_INFO, PUBLICATION_INFO_DDL
from bus_checker.publish.records import record_publication

logger = logging.getLogger(__name__)


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _attach(connection: Any, source: Path, timeout: float) -> None:
    import duckdb

    deadline = time.monotonic() + timeout
    delay = 0.2
    while True:
        try:
            connection.execute(f"ATTACH {_sql_string(str(source))} AS warehouse (READ_ONLY)")
            return
        except duckdb.IOException as error:
            if "lock" not in str(error).lower() or time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 5.0)


def _replace(temporary: Path, target: Path, timeout: float = 30.0) -> None:
    """Atomic rename. On Windows a reader holding the old file open can block it briefly."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.replace(temporary, target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)


def publish_snapshot(settings: Settings) -> dict[str, Any]:
    import duckdb

    if settings.backend != "duckdb":
        raise ValueError("Snapshot publication applies to the DuckDB backend only")
    source = settings.duckdb_path
    target = settings.snapshot_path
    if not source.is_file():
        raise FileNotFoundError(f"Warehouse not found: {source}")
    if target.resolve() == source.resolve():
        raise ValueError("BUS_SNAPSHOT_PATH must differ from BUS_DUCKDB_PATH")
    target.parent.mkdir(parents=True, exist_ok=True)

    publication_id = new_uuid()
    started = datetime.now(UTC)
    temporary = target.with_name(f".{target.name}.{publication_id[:8]}.tmp")
    counts: dict[str, int] = {}
    try:
        connection = duckdb.connect(str(temporary))
        try:
            connection.execute("SET TimeZone = 'UTC'")
            _attach(connection, source, settings.lock_timeout)
            available = {
                row[0]
                for row in connection.execute(
                    "SELECT table_name FROM duckdb_tables() WHERE database_name = 'warehouse' AND schema_name = ?",
                    [MARTS_SCHEMA],
                ).fetchall()
            }
            missing = [t.name for t in MARTS if t.name not in available]
            if missing:
                raise RuntimeError(f"Marts not built yet: {', '.join(missing)}. Run the build first.")
            connection.execute(f"CREATE SCHEMA {MARTS_SCHEMA}")
            for table in MARTS:
                connection.execute(
                    f'CREATE TABLE {MARTS_SCHEMA}."{table.name}" AS '
                    f'SELECT * FROM warehouse.{MARTS_SCHEMA}."{table.name}"'
                )
                row = connection.execute(f'SELECT count(*) FROM {MARTS_SCHEMA}."{table.name}"').fetchone()
                counts[table.name] = int(row[0]) if row else 0
            connection.execute(f"CREATE TABLE {MARTS_SCHEMA}.{PUBLICATION_INFO} ({PUBLICATION_INFO_DDL['duckdb']})")
            connection.execute(
                f"INSERT INTO {MARTS_SCHEMA}.{PUBLICATION_INFO} "
                "SELECT ?, 'snapshot', 'duckdb', ?, max(service_date), max(ingested_at) "
                f"FROM {MARTS_SCHEMA}.network_daily WHERE events > 0",
                [publication_id, datetime.now(UTC)],
            )
            connection.execute("DETACH warehouse")
            connection.execute("CHECKPOINT")
        finally:
            connection.close()
        _replace(temporary, target)
    except Exception as error:
        record_publication(settings, publication_id, "snapshot", started, "failed", counts, error)
        raise
    finally:
        temporary.unlink(missing_ok=True)
        Path(str(temporary) + ".wal").unlink(missing_ok=True)
    record_publication(settings, publication_id, "snapshot", started, "success", counts)
    size = target.stat().st_size
    logger.info("Published dashboard snapshot %s (%.1f MB)", target.name, size / 1e6)
    return {"publication_id": publication_id, "path": str(target), "bytes": size, "tables": counts}
