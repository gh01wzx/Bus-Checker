import os
import re
from contextlib import contextmanager
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


PARAMETER_PATTERN = re.compile(r"(?<!:):([a-zA-Z_]\w*)")
INSERT_BATCH_SIZE = 1000


def backend() -> str:
    value = os.getenv(
        "BUS_BACKEND", "postgres" if os.getenv("SUPABASE_DB_URL") else "duckdb"
    )
    if value not in {"postgres", "duckdb"}:
        raise ValueError("BUS_BACKEND must be postgres or duckdb")
    return value


def duckdb_path() -> str:
    return str(
        Path(os.getenv("BUS_DUCKDB_PATH", str(ROOT / "bus_data.duckdb"))).resolve()
    )


class Connection:

    def __init__(self, connection, kind):
        self.connection, self.kind = connection, kind

    def execute(self, sql, params=None):
        if self.kind == "duckdb":
            sql = PARAMETER_PATTERN.sub(r"$\1", sql)
            return self.connection.execute(sql, params or {})
        return self.connection.execute(text(sql), params or {})

    def frame(self, sql, params=None):
        result = self.execute(sql, params)
        if self.kind == "duckdb":
            return result.fetchdf()
        return pd.DataFrame(result.fetchall(), columns=result.keys())

    def many(self, sql, rows):
        if not rows:
            return
        if self.kind == "duckdb":
            keys = PARAMETER_PATTERN.findall(sql)
            sql = PARAMETER_PATTERN.sub("?", sql)
            self.connection.executemany(
                sql, [[row[key] for key in keys] for row in rows]
            )
        else:
            for offset in range(0, len(rows), INSERT_BATCH_SIZE):
                self.connection.execute(
                    text(sql), rows[offset : offset + INSERT_BATCH_SIZE]
                )


@contextmanager
def connect(write=False):
    if backend() == "duckdb":
        import duckdb

        conn = duckdb.connect(duckdb_path(), read_only=not write)
        try:
            conn.execute("SET TimeZone='UTC'")
            if write:
                conn.execute("BEGIN")
            yield Connection(conn, "duckdb")
            if write:
                conn.execute("COMMIT")
        except Exception:
            if write:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
    else:
        url = os.getenv("SUPABASE_DB_URL")
        if not url:
            raise ValueError("SUPABASE_DB_URL is required for BUS_BACKEND=postgres")
        engine = create_engine(url)
        try:
            with engine.begin() if write else engine.connect() as conn:
                conn.execute(text("SET TIME ZONE 'UTC'"))
                yield Connection(conn, "postgres")
        finally:
            engine.dispose()


def read_frame(sql: str, params: dict | None = None) -> pd.DataFrame:
    with connect() as conn:
        return conn.frame(sql, params)


def bootstrap(conn):
    statements = [
        """CREATE TABLE IF NOT EXISTS bus_raw_batches (
            batch_id VARCHAR PRIMARY KEY, captured_at TIMESTAMP WITH TIME ZONE NOT NULL,
            loaded_at TIMESTAMP WITH TIME ZONE NOT NULL, payload VARCHAR NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS bus_ingestion_runs (
            run_id VARCHAR PRIMARY KEY, batch_id VARCHAR, started_at TIMESTAMP WITH TIME ZONE,
            finished_at TIMESTAMP WITH TIME ZONE, status VARCHAR, accepted_rows BIGINT,
            rejected_rows BIGINT, duplicate_rows BIGINT, error_code VARCHAR)""",
        """CREATE TABLE IF NOT EXISTS bus_quarantine (
            rejection_id VARCHAR PRIMARY KEY, batch_id VARCHAR, reason VARCHAR, payload VARCHAR)""",
        """CREATE TABLE IF NOT EXISTS bus_observations (
            observation_id VARCHAR PRIMARY KEY, batch_id VARCHAR NOT NULL,
            captured_at TIMESTAMP WITH TIME ZONE NOT NULL,
            loaded_at TIMESTAMP WITH TIME ZONE NOT NULL,
            route_id VARCHAR NOT NULL, trip_id VARCHAR NOT NULL, direction_id BIGINT,
            stop_id VARCHAR, stop_sequence BIGINT, delay BIGINT NOT NULL,
            observation_type VARCHAR NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS trip_punctuality (
            captured_at TIMESTAMP WITH TIME ZONE, route_id VARCHAR, trip_id VARCHAR,
            delay BIGINT, direction_id BIGINT)""",
        """CREATE TABLE IF NOT EXISTS stop_punctuality (
            captured_at TIMESTAMP WITH TIME ZONE, route_id VARCHAR, trip_id VARCHAR,
            stop_id VARCHAR, stop_sequence BIGINT, delay BIGINT)""",
    ]
    for sql in statements:
        conn.execute(sql)
