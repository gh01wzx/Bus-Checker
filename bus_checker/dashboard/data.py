"""Query execution for the dashboard: pooled, cached and failure-tolerant."""

from __future__ import annotations

import logging
from collections.abc import Hashable
from typing import Any

import pandas as pd
import streamlit as st

from bus_checker.config import get_settings
from bus_checker.warehouse import DuckDBWarehouse, PostgresWarehouse

logger = logging.getLogger(__name__)
CACHE_TTL_SEC = 60


class DataUnavailable(RuntimeError):
    """The dashboard source cannot answer (not published yet, unreachable, or missing table)."""


def source_version() -> str:
    """Changes whenever a new DuckDB snapshot is published, invalidating cached queries."""
    settings = get_settings()
    if settings.backend == "duckdb":
        path = settings.snapshot_path
        return str(path.stat().st_mtime_ns) if path.exists() else "missing"
    return "postgres"


@st.cache_resource(show_spinner=False)
def _pool(dsn: str) -> Any:
    from psycopg2.pool import ThreadedConnectionPool

    return ThreadedConnectionPool(1, 4, dsn, connect_timeout=10, application_name="bus-checker-dashboard")


def _postgres_frame(sql: str, params: dict[str, Any]) -> pd.DataFrame:
    import psycopg2

    pool = _pool(get_settings().postgres_dsn)
    connection = pool.getconn()
    healthy = True
    try:
        if not (connection.autocommit and connection.readonly):
            connection.set_session(readonly=True, autocommit=True)
            with connection.cursor() as cursor:
                cursor.execute("SET TIME ZONE 'UTC'")
        return PostgresWarehouse.from_connection(connection).frame(sql, params)
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        healthy = False
        raise
    finally:
        pool.putconn(connection, close=not healthy or connection.closed != 0)


def _duckdb_frame(sql: str, params: dict[str, Any]) -> pd.DataFrame:
    warehouse = DuckDBWarehouse(get_settings().snapshot_path, read_only=True, lock_timeout=10)
    try:
        return warehouse.frame(sql, params)
    finally:
        warehouse.close()


@st.cache_data(ttl=CACHE_TTL_SEC, show_spinner=False, max_entries=1024)
def _cached(sql: str, params: tuple[tuple[str, Hashable], ...], version: str) -> pd.DataFrame:
    values = dict(params)
    if get_settings().backend == "duckdb":
        return _duckdb_frame(sql, values)
    return _postgres_frame(sql, values)


def query(sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    """Run a read-only query against the dashboard source, cached per publication."""
    key = tuple(sorted((params or {}).items()))
    try:
        return _cached(sql, key, source_version()).copy()
    except FileNotFoundError as error:
        raise DataUnavailable("No dashboard data has been published yet.") from error
    except Exception as error:
        logger.warning("Dashboard query failed: %s", type(error).__name__)
        raise DataUnavailable(f"The data source could not answer ({type(error).__name__}).") from error


def clear_cache() -> None:
    _cached.clear()


def in_list(prefix: str, values: list[Any] | tuple[Any, ...]) -> tuple[str, dict[str, Any]]:
    """Expand a list into named parameters: ``(:p0, :p1)`` plus their values."""
    if not values:
        return "(NULL)", {}
    names = {f"{prefix}{i}": value for i, value in enumerate(values)}
    return "(" + ", ".join(f":{name}" for name in names) + ")", names
