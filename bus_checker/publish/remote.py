"""Publish the dashboard marts to a remote PostgreSQL database (e.g. Supabase free tier).

The publication runs in a single remote transaction, so the online dashboard always sees
one complete publication. Date-partitioned marts are synchronised incrementally: the last
``BUS_PUBLISH_LOOKBACK_DAYS`` are always replaced, older dates only when their row count
differs, and dates beyond each table's retention window are deleted to respect the free
tier's storage limit. Small tables are replaced in full.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from bus_checker.config import ConfigError, Settings
from bus_checker.ids import new_uuid
from bus_checker.publish.contract import (
    MARTS,
    MARTS_SCHEMA,
    PUBLICATION_INFO,
    PUBLICATION_INFO_DDL,
    PUBLICATION_LOG,
    MartTable,
    ddl_type,
    pg_type,
)
from bus_checker.publish.records import record_publication
from bus_checker.warehouse import (
    Warehouse,
    open_dashboard_source,
    open_url,
    open_warehouse,
    quote_identifier,
)

logger = logging.getLogger(__name__)
PUBLICATION_LOG_KEEP = 500
PUBLICATION_STATE = "publication_state"


def _columns(warehouse: Warehouse, table: str) -> list[tuple[str, str]]:
    rows = warehouse.fetchall(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = :schema AND table_name = :table ORDER BY ordinal_position",
        {"schema": MARTS_SCHEMA, "table": table},
    )
    return [(name, pg_type(kind)) for name, kind in rows]


def _ref(table: str) -> str:
    return f"{quote_identifier(MARTS_SCHEMA)}.{quote_identifier(table)}"


def _create(target: Warehouse, table: MartTable, columns: list[tuple[str, str]]) -> None:
    definition = ", ".join(f"{quote_identifier(name)} {ddl_type(target.kind, kind)}" for name, kind in columns)
    target.execute(f"DROP TABLE IF EXISTS {_ref(table.name)}")
    target.execute(f"CREATE TABLE {_ref(table.name)} ({definition})")
    if table.date_column and target.kind == "postgres":
        target.execute(
            f"CREATE INDEX {quote_identifier('ix_' + table.name + '_' + table.date_column)} "
            f"ON {_ref(table.name)} ({quote_identifier(table.date_column)})"
        )


def _window_days(settings: Settings, table: MartTable) -> int:
    return {
        "daily": settings.publish_daily_days,
        "hourly": settings.publish_hourly_days,
        "detail": settings.publish_detail_days,
    }[table.window or "daily"]


def _copy(
    source: Warehouse,
    target: Warehouse,
    table: MartTable,
    names: list[str],
    where: str = "",
    params: dict[str, Any] | None = None,
) -> int:
    column_list = ", ".join(quote_identifier(n) for n in names)
    total = 0
    for rows in source.iterate(f"SELECT {column_list} FROM {_ref(table.name)} {where}", params):
        total += target.copy_rows(_ref(table.name), names, rows)
    return total


def _load_state(target: Warehouse) -> dict[str, str]:
    ddl = "table_name text PRIMARY KEY, fingerprint text NOT NULL"
    if target.kind == "duckdb":
        ddl = "table_name VARCHAR PRIMARY KEY, fingerprint VARCHAR NOT NULL"
    target.execute(f"CREATE TABLE IF NOT EXISTS {_ref(PUBLICATION_STATE)} ({ddl})")
    return dict(target.fetchall(f"SELECT table_name, fingerprint FROM {_ref(PUBLICATION_STATE)}"))


def _save_state(target: Warehouse, state: dict[str, str]) -> None:
    target.execute(f"DELETE FROM {_ref(PUBLICATION_STATE)}")
    for name, fingerprint in sorted(state.items()):
        target.execute(
            f"INSERT INTO {_ref(PUBLICATION_STATE)} VALUES (:name, :fingerprint)",
            {"name": name, "fingerprint": fingerprint},
        )


def _sync_small(
    source: Warehouse,
    target: Warehouse,
    table: MartTable,
    names: list[str],
    fresh: bool,
    state: dict[str, str],
) -> dict[str, Any]:
    """Replace a small table, skipping the write when its content is unchanged."""
    column_list = ", ".join(quote_identifier(n) for n in names)
    order = ", ".join(str(i + 1) for i in range(len(names)))
    digest = hashlib.sha256()
    rows: list[tuple] = []
    for chunk in source.iterate(f"SELECT {column_list} FROM {_ref(table.name)} ORDER BY {order}"):
        rows.extend(chunk)
        for row in chunk:
            digest.update(repr(tuple(str(v) for v in row)).encode("utf-8"))
    fingerprint = f"{len(rows)}:{digest.hexdigest()}"
    if not fresh and state.get(table.name) == fingerprint:
        return {"rows": 0, "unchanged": True}
    target.execute(f"DELETE FROM {_ref(table.name)}")
    copied = target.copy_rows(_ref(table.name), names, rows) if rows else 0
    state[table.name] = fingerprint
    return {"rows": copied, "replaced": True}


def _sync_partitioned(
    settings: Settings,
    source: Warehouse,
    target: Warehouse,
    table: MartTable,
    names: list[str],
    fresh: bool,
) -> dict[str, Any]:
    assert table.date_column
    column = quote_identifier(table.date_column)
    latest = source.scalar(f"SELECT max({column}) FROM {_ref(table.name)}")
    if latest is None:
        removed = target.execute(f"DELETE FROM {_ref(table.name)}")
        return {"rows": 0, "dates": 0, "removed": removed}
    if isinstance(latest, datetime):
        latest = latest.date()
    start: date = latest - timedelta(days=_window_days(settings, table) - 1)
    lookback: date = latest - timedelta(days=settings.publish_lookback_days - 1)

    local = dict(
        source.fetchall(
            f"SELECT {column}, count(*) FROM {_ref(table.name)} WHERE {column} >= :start GROUP BY 1",
            {"start": start},
        )
    )
    remote = {} if fresh else dict(target.fetchall(f"SELECT {column}, count(*) FROM {_ref(table.name)} GROUP BY 1"))
    local = {(k.date() if isinstance(k, datetime) else k): v for k, v in local.items()}
    remote = {(k.date() if isinstance(k, datetime) else k): v for k, v in remote.items()}

    removed = target.execute(f"DELETE FROM {_ref(table.name)} WHERE {column} < :start", {"start": start})
    stale = [d for d in remote if d >= start and d not in local]
    changed = sorted(d for d, n in local.items() if d >= lookback or remote.get(d) != n)
    rows = 0
    for day in sorted(set(stale) | set(changed)):
        removed += target.execute(f"DELETE FROM {_ref(table.name)} WHERE {column} = :day", {"day": day})
    for day in changed:
        rows += _copy(source, target, table, names, f"WHERE {column} = :day", {"day": day})
    return {"rows": rows, "dates": len(changed), "removed": removed, "window_start": start.isoformat()}


def sync_remote(settings: Settings, *, full: bool = False) -> dict[str, Any]:
    if not settings.publish_url:
        raise ConfigError("BUS_PUBLISH_URL is not set")
    publication_id = new_uuid()
    started = datetime.now(UTC)
    report: dict[str, Any] = {}
    # DuckDB: read the published snapshot (never contends with the writer).
    # PostgreSQL: a read-only transaction, so large tables stream via a server-side cursor.
    source = (
        open_dashboard_source(settings) if settings.backend == "duckdb" else open_warehouse(settings, read_only=True)
    )
    try:
        target = open_url(settings.publish_url)
    except Exception as error:
        source.close()
        record_publication(settings, publication_id, "remote", started, "failed", report, error)
        raise
    try:
        target.execute(f"CREATE SCHEMA IF NOT EXISTS {quote_identifier(MARTS_SCHEMA)}")
        state = _load_state(target)
        for table in MARTS:
            columns = _columns(source, table.name)
            if not columns:
                raise RuntimeError(f"Source mart {table.name} does not exist; build and publish first")
            names = [name for name, _ in columns]
            fresh = full or _columns(target, table.name) != columns
            if fresh:
                _create(target, table, columns)
            if table.date_column is None:
                report[table.name] = _sync_small(source, target, table, names, fresh, state)
            else:
                report[table.name] = _sync_partitioned(settings, source, target, table, names, fresh)
            report[table.name]["recreated"] = fresh

        _save_state(target, state)
        data_through, latest_ingested = (
            source.fetchall(f"SELECT max(service_date), max(ingested_at) FROM {_ref('network_daily')} WHERE events > 0")
            or [(None, None)]
        )[0]
        published_at = datetime.now(UTC)
        target.execute(f"DROP TABLE IF EXISTS {_ref(PUBLICATION_INFO)}")
        target.execute(f"CREATE TABLE {_ref(PUBLICATION_INFO)} ({PUBLICATION_INFO_DDL[target.kind]})")
        target.execute(
            f"INSERT INTO {_ref(PUBLICATION_INFO)} VALUES (:id, 'remote', :backend, :published, :through, :ingested)",
            {
                "id": publication_id,
                "backend": settings.backend,
                "published": published_at,
                "through": data_through,
                "ingested": latest_ingested,
            },
        )
        log_ddl = "publication_id text, published_at timestamptz, details text"
        if target.kind == "duckdb":
            log_ddl = "publication_id VARCHAR, published_at TIMESTAMPTZ, details VARCHAR"
        target.execute(f"CREATE TABLE IF NOT EXISTS {_ref(PUBLICATION_LOG)} ({log_ddl})")
        target.execute(
            f"INSERT INTO {_ref(PUBLICATION_LOG)} VALUES (:id, :published, :details)",
            {"id": publication_id, "published": published_at, "details": json.dumps(report, default=str)},
        )
        target.execute(
            f"DELETE FROM {_ref(PUBLICATION_LOG)} WHERE published_at < ("
            f"SELECT min(published_at) FROM (SELECT published_at FROM {_ref(PUBLICATION_LOG)} "
            f"ORDER BY published_at DESC LIMIT {PUBLICATION_LOG_KEEP}) AS recent)"
        )
        target.commit()
    except Exception as error:
        target.rollback()
        record_publication(settings, publication_id, "remote", started, "failed", report, error)
        raise
    finally:
        target.close()
        source.close()
    record_publication(settings, publication_id, "remote", started, "success", report)
    total = sum(item.get("rows", 0) for item in report.values())
    logger.info("Remote publication %s committed: %s rows copied", publication_id, total)
    return {"publication_id": publication_id, "rows_copied": total, "tables": report}
