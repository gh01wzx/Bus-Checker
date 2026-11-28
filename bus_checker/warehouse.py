"""A small, explicit database layer shared by the pipeline and the dashboard.

Both backends accept SQL with ``:name`` parameters. Bulk data enters through
:meth:`Warehouse.stage`, which creates a typed temporary table, so the same
``INSERT ... SELECT`` statements run unchanged on DuckDB and PostgreSQL.
"""

from __future__ import annotations

import io
import logging
import re
import time
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from bus_checker.config import Settings

logger = logging.getLogger(__name__)

PARAMETER = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")
COPY_CHUNK_ROWS = 50_000

# Logical type -> (DuckDB DDL, PostgreSQL DDL)
SQL_TYPES: dict[str, tuple[str, str]] = {
    "uuid": ("UUID", "uuid"),
    "text": ("VARCHAR", "text"),
    "smallint": ("SMALLINT", "smallint"),
    "int": ("INTEGER", "integer"),
    "bigint": ("BIGINT", "bigint"),
    "double": ("DOUBLE", "double precision"),
    "bool": ("BOOLEAN", "boolean"),
    "date": ("DATE", "date"),
    "timestamptz": ("TIMESTAMPTZ", "timestamptz"),
}


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    nullable: bool = True

    def __post_init__(self) -> None:
        if self.type not in SQL_TYPES:
            raise ValueError(f"Unknown column type {self.type!r}")


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def qualified(schema: str, name: str) -> str:
    return f"{quote_identifier(schema)}.{quote_identifier(name)}"


def to_duckdb_sql(sql: str) -> str:
    return PARAMETER.sub(r"$\1", sql)


def to_psycopg_sql(sql: str, has_params: bool) -> str:
    if not has_params:
        return sql
    return PARAMETER.sub(r"%(\1)s", sql.replace("%", "%%"))


def _csv_field(value: Any) -> str:
    if value is None:
        return "\\N"
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()  # numpy scalar
    if isinstance(value, bool):
        return "t" if value else "f"
    if isinstance(value, float) and value != value:  # NaN from pandas means missing
        return "\\N"
    if isinstance(value, (datetime, date)):
        value = value.isoformat()
    text = str(value)
    return '"' + text.replace('"', '""') + '"'


def _csv_chunks(rows: Iterable[Sequence[Any]]) -> Iterator[io.StringIO]:
    buffer = io.StringIO()
    count = 0
    for row in rows:
        buffer.write(",".join(_csv_field(value) for value in row))
        buffer.write("\n")
        count += 1
        if count >= COPY_CHUNK_ROWS:
            buffer.seek(0)
            yield buffer
            buffer, count = io.StringIO(), 0
    if count:
        buffer.seek(0)
        yield buffer


def normalise_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Give both backends the same pandas dtypes for dates and timestamps."""
    for column in frame.columns:
        series = frame[column]
        if series.dtype != object:
            continue
        sample = series.dropna()
        if sample.empty:
            continue
        first = sample.iloc[0]
        if isinstance(first, datetime):
            frame[column] = pd.to_datetime(series, utc=first.tzinfo is not None)
        elif isinstance(first, date):
            frame[column] = pd.to_datetime(series)
    return frame


class Warehouse:
    """Common interface. Instances are not thread-safe; open one per unit of work."""

    kind: str

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        """Run a statement and return the affected row count when the backend reports one."""
        raise NotImplementedError

    def fetchall(self, sql: str, params: dict[str, Any] | None = None) -> list[tuple]:
        raise NotImplementedError

    def iterate(
        self, sql: str, params: dict[str, Any] | None = None, size: int = COPY_CHUNK_ROWS
    ) -> Iterator[list[tuple]]:
        raise NotImplementedError

    def columns(self, sql: str, params: dict[str, Any] | None = None) -> list[str]:
        raise NotImplementedError

    def frame(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        raise NotImplementedError

    def stage(self, name: str, columns: Sequence[Column], rows: Sequence[Sequence[Any]]) -> None:
        """Create (or replace) a typed temporary table called ``name`` holding ``rows``."""
        raise NotImplementedError

    def copy_rows(self, table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> int:
        """Bulk append rows to an existing table."""
        raise NotImplementedError

    def table_exists(self, schema: str, name: str) -> bool:
        rows = self.fetchall(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = :schema AND table_name = :name",
            {"schema": schema, "name": name},
        )
        return bool(rows)

    def scalar(self, sql: str, params: dict[str, Any] | None = None) -> Any:
        rows = self.fetchall(sql, params)
        return rows[0][0] if rows else None

    def drop_stage(self, name: str) -> None:
        self.execute(f"DROP TABLE IF EXISTS {quote_identifier(name)}")

    def sql_type(self, logical: str) -> str:
        duck, pg = SQL_TYPES[logical]
        return duck if self.kind == "duckdb" else pg

    def commit(self) -> None:
        raise NotImplementedError

    def rollback(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class DuckDBWarehouse(Warehouse):
    kind = "duckdb"

    def __init__(
        self,
        path: Path,
        *,
        read_only: bool = False,
        autocommit: bool = False,
        lock_timeout: float = 60.0,
    ) -> None:
        import duckdb

        if not read_only:
            path.parent.mkdir(parents=True, exist_ok=True)
        elif not path.exists():
            raise FileNotFoundError(f"DuckDB database not found: {path}")
        deadline = time.monotonic() + lock_timeout
        delay = 0.2
        while True:
            try:
                self.conn = duckdb.connect(str(path), read_only=read_only)
                break
            except duckdb.IOException as error:
                if "lock" not in str(error).lower() or time.monotonic() >= deadline:
                    raise
                logger.info("Waiting for DuckDB lock on %s", path.name)
                time.sleep(delay)
                delay = min(delay * 2, 5.0)
        self.read_only = read_only
        self.in_transaction = False
        self.conn.execute("SET TimeZone = 'UTC'")
        if not read_only and not autocommit:
            self.conn.execute("BEGIN TRANSACTION")
            self.in_transaction = True

    def _run(self, sql: str, params: dict[str, Any] | None):
        return self.conn.execute(to_duckdb_sql(sql), params or None)

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        result = self._run(sql, params)
        try:
            row = result.fetchone()
        except Exception:  # DDL statements have no result set
            return 0
        if row and len(row) == 1 and isinstance(row[0], int):
            return row[0]
        return 0

    def fetchall(self, sql: str, params: dict[str, Any] | None = None) -> list[tuple]:
        return self._run(sql, params).fetchall()

    def iterate(
        self, sql: str, params: dict[str, Any] | None = None, size: int = COPY_CHUNK_ROWS
    ) -> Iterator[list[tuple]]:
        result = self._run(sql, params)
        while rows := result.fetchmany(size):
            yield rows

    def columns(self, sql: str, params: dict[str, Any] | None = None) -> list[str]:
        result = self._run(f"SELECT * FROM ({sql}) AS q LIMIT 0", params)
        return [item[0] for item in result.description or []]

    def frame(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        return normalise_frame(self._run(sql, params).fetchdf())

    def stage(self, name: str, columns: Sequence[Column], rows: Sequence[Sequence[Any]]) -> None:
        import pyarrow as pa

        arrow_types = {
            "uuid": pa.string(),
            "text": pa.string(),
            "smallint": pa.int16(),
            "int": pa.int32(),
            "bigint": pa.int64(),
            "double": pa.float64(),
            "bool": pa.bool_(),
            "date": pa.date32(),
            "timestamptz": pa.timestamp("us", tz="UTC"),
        }
        table = pa.table(
            {
                column.name: pa.array([row[i] for row in rows], type=arrow_types[column.type])
                for i, column in enumerate(columns)
            }
        )
        view = f"__arrow_{name}"
        self.conn.register(view, table)
        try:
            casts = ", ".join(
                f"CAST({quote_identifier(c.name)} AS {SQL_TYPES[c.type][0]}) AS {quote_identifier(c.name)}"
                for c in columns
            )
            self.conn.execute(
                f"CREATE OR REPLACE TEMP TABLE {quote_identifier(name)} AS SELECT {casts} FROM {quote_identifier(view)}"
            )
        finally:
            self.conn.unregister(view)

    def copy_rows(self, table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> int:
        import pyarrow as pa

        column_list = ", ".join(quote_identifier(c) for c in columns)
        total = 0

        def flush(batch: list[Sequence[Any]]) -> int:
            arrow = pa.table({c: pa.array([r[i] for r in batch]) for i, c in enumerate(columns)})
            self.conn.register("__arrow_copy", arrow)
            try:
                self.conn.execute(f"INSERT INTO {table} ({column_list}) SELECT {column_list} FROM __arrow_copy")
            finally:
                self.conn.unregister("__arrow_copy")
            return len(batch)

        batch: list[Sequence[Any]] = []
        for row in rows:
            batch.append(row)
            if len(batch) >= COPY_CHUNK_ROWS:
                total += flush(batch)
                batch = []
        if batch:
            total += flush(batch)
        return total

    def commit(self) -> None:
        if self.in_transaction:
            self.conn.execute("COMMIT")
            self.in_transaction = False

    def rollback(self) -> None:
        if self.in_transaction:
            self.conn.execute("ROLLBACK")
            self.in_transaction = False

    def close(self) -> None:
        self.conn.close()


_PG_TYPES_REGISTERED = False


def _register_pg_types() -> None:
    """Return NUMERIC as float so pandas, plotting and JSON behave like DuckDB."""
    global _PG_TYPES_REGISTERED
    if _PG_TYPES_REGISTERED:
        return
    import psycopg2.extensions as ext

    numeric_as_float = ext.new_type(
        ext.DECIMAL.values,
        "BUS_NUMERIC_AS_FLOAT",
        lambda value, cursor: float(value) if value is not None else None,
    )
    ext.register_type(numeric_as_float)
    _PG_TYPES_REGISTERED = True


class PostgresWarehouse(Warehouse):
    kind = "postgres"

    def __init__(
        self,
        dsn: str,
        *,
        read_only: bool = False,
        autocommit: bool = False,
        application_name: str = "bus-checker",
    ) -> None:
        import psycopg2

        _register_pg_types()
        self.conn = psycopg2.connect(dsn, connect_timeout=10, application_name=application_name)
        self.conn.set_session(readonly=read_only, autocommit=autocommit)
        with self.conn.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'UTC'")
        self._cursor_seq = 0

    @classmethod
    def from_connection(cls, connection: Any) -> PostgresWarehouse:
        """Wrap an existing (for example pooled) psycopg2 connection."""
        _register_pg_types()
        instance = cls.__new__(cls)
        instance.conn = connection
        instance._cursor_seq = 0
        return instance

    def _cursor(self):
        return self.conn.cursor()

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        with self._cursor() as cursor:
            cursor.execute(to_psycopg_sql(sql, bool(params)), params or None)
            return max(cursor.rowcount, 0)

    def fetchall(self, sql: str, params: dict[str, Any] | None = None) -> list[tuple]:
        with self._cursor() as cursor:
            cursor.execute(to_psycopg_sql(sql, bool(params)), params or None)
            return cursor.fetchall()

    def iterate(
        self, sql: str, params: dict[str, Any] | None = None, size: int = COPY_CHUNK_ROWS
    ) -> Iterator[list[tuple]]:
        if self.conn.autocommit:
            with self._cursor() as cursor:
                cursor.execute(to_psycopg_sql(sql, bool(params)), params or None)
                while rows := cursor.fetchmany(size):
                    yield rows
            return
        self._cursor_seq += 1
        with self.conn.cursor(name=f"bus_stream_{self._cursor_seq}") as cursor:
            cursor.itersize = size
            cursor.execute(to_psycopg_sql(sql, bool(params)), params or None)
            while rows := cursor.fetchmany(size):
                yield rows

    def columns(self, sql: str, params: dict[str, Any] | None = None) -> list[str]:
        with self._cursor() as cursor:
            cursor.execute(
                to_psycopg_sql(f"SELECT * FROM ({sql}) AS q LIMIT 0", bool(params)),
                params or None,
            )
            return [item[0] for item in cursor.description or []]

    def frame(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        with self._cursor() as cursor:
            cursor.execute(to_psycopg_sql(sql, bool(params)), params or None)
            names = [item[0] for item in cursor.description or []]
            frame = pd.DataFrame.from_records(cursor.fetchall(), columns=names)
        return normalise_frame(frame)

    def stage(self, name: str, columns: Sequence[Column], rows: Sequence[Sequence[Any]]) -> None:
        ident = quote_identifier(name)
        definition = ", ".join(f"{quote_identifier(c.name)} {SQL_TYPES[c.type][1]}" for c in columns)
        self.execute(f"DROP TABLE IF EXISTS {ident}")
        self.execute(f"CREATE TEMP TABLE {ident} ({definition}) ON COMMIT DROP")
        self.copy_rows(ident, [c.name for c in columns], rows)

    def copy_rows(self, table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> int:
        column_list = ", ".join(quote_identifier(c) for c in columns)
        statement = f"COPY {table} ({column_list}) FROM STDIN WITH (FORMAT csv, NULL '\\N')"
        total = 0
        with self._cursor() as cursor:
            for chunk in _csv_chunks(rows):
                cursor.copy_expert(statement, chunk)
                total += max(cursor.rowcount, 0)
        return total

    def commit(self) -> None:
        if not self.conn.autocommit:
            self.conn.commit()

    def rollback(self) -> None:
        if not self.conn.autocommit and not self.conn.closed:
            self.conn.rollback()

    def close(self) -> None:
        if not self.conn.closed:
            self.conn.close()


def open_warehouse(settings: Settings, *, read_only: bool = False, autocommit: bool = False) -> Warehouse:
    """Open the pipeline warehouse (the writer's database)."""
    if settings.backend == "duckdb":
        return DuckDBWarehouse(
            settings.duckdb_path,
            read_only=read_only,
            autocommit=autocommit,
            lock_timeout=settings.lock_timeout,
        )
    return PostgresWarehouse(settings.postgres_dsn, read_only=read_only, autocommit=autocommit)


def open_url(url: str, *, read_only: bool = False) -> Warehouse:
    """Open a database named by URL: ``postgresql://...`` or a DuckDB file path."""
    if url.startswith(("postgres://", "postgresql://", "postgresql+")):
        from bus_checker.config import normalise_postgres_url

        return PostgresWarehouse(normalise_postgres_url(url), read_only=read_only)
    path = url.removeprefix("duckdb:///").removeprefix("duckdb://")
    return DuckDBWarehouse(Path(path), read_only=read_only)


def open_dashboard_source(settings: Settings) -> Warehouse:
    """Open the relation set the dashboard reads: the DuckDB snapshot or Postgres marts."""
    if settings.backend == "duckdb":
        return DuckDBWarehouse(settings.snapshot_path, read_only=True, lock_timeout=10)
    return PostgresWarehouse(settings.postgres_dsn, read_only=True, autocommit=True)


@contextmanager
def transaction(warehouse: Warehouse) -> Iterator[Warehouse]:
    """Commit on success, roll back on error, always close."""
    try:
        yield warehouse
        warehouse.commit()
    except BaseException:
        try:
            warehouse.rollback()
        except Exception:  # pragma: no cover - the original error matters more
            logger.exception("Rollback failed")
        raise
    finally:
        warehouse.close()


@contextmanager
def session(settings: Settings, *, read_only: bool = False, autocommit: bool = False) -> Iterator[Warehouse]:
    with transaction(open_warehouse(settings, read_only=read_only, autocommit=autocommit)) as wh:
        yield wh
