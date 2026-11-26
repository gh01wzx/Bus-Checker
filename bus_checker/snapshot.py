"""Publish a closed, checkpointed DuckDB file for the dashboard on local Docker."""

import os
import shutil
import tempfile
from pathlib import Path

import duckdb

from bus_checker.database import backend, duckdb_path


def publish_snapshot() -> None:
    if backend() != "duckdb":
        raise ValueError("Snapshot publication requires DuckDB")
    source = Path(duckdb_path())
    directory = Path(os.environ["BUS_SNAPSHOT_DIR"])
    target = directory / source.name  # dbt views can refer to the catalog by name.
    if target.resolve() == source:
        raise ValueError("Use a separate directory for dashboard snapshots")
    if not source.is_file():
        raise FileNotFoundError(source)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        # Hold the writer lock until the copy finishes. No other process can
        # change the database between the checkpoint and the end of the copy.
        with duckdb.connect(str(source)) as connection:
            connection.execute("CHECKPOINT")
            with tempfile.NamedTemporaryFile(dir=directory, delete=False) as output:
                temporary = Path(output.name)
                with source.open("rb") as data:
                    shutil.copyfileobj(data, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
