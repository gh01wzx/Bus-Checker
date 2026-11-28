from __future__ import annotations

import json
import os
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(FIXTURES))

import feeds  # noqa: E402

from bus_checker.config import Settings, reset_settings  # noqa: E402

CLEARED = (
    "BUS_POSTGRES_URL",
    "BUS_PUBLISH_URL",
    "PGHOST",
    "PGPORT",
    "PGUSER",
    "PGPASSWORD",
    "PGDATABASE",
)


@pytest.fixture
def now() -> datetime:
    """Today at 02:00 UTC (14:00/15:00 in Auckland): far from local midnight, so a second
    snapshot minutes later stays on the same service day whenever the suite runs."""
    return datetime.now(UTC).replace(hour=2, minute=0, second=0, microsecond=0)


@pytest.fixture
def feed_bytes():
    def build(name: str, moment: datetime, **kwargs) -> bytes:
        return json.dumps(getattr(feeds, name)(moment, **kwargs)).encode()

    return build


@pytest.fixture
def duckdb_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Isolated DuckDB warehouse, snapshot, archive and dbt target directory."""
    for name in CLEARED:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BUS_BACKEND", "duckdb")
    monkeypatch.setenv("BUS_DUCKDB_PATH", str(tmp_path / "warehouse" / "bus.duckdb"))
    monkeypatch.setenv("BUS_SNAPSHOT_PATH", str(tmp_path / "published" / "bus_dashboard.duckdb"))
    monkeypatch.setenv("BUS_ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setenv("BUS_DBT_TARGET_DIR", str(tmp_path / "dbt-target"))
    monkeypatch.setenv("AT_SUB_KEY", "test-key")
    monkeypatch.setenv("BUS_LOCK_TIMEOUT", "5")
    reset_settings()
    yield Settings.from_env(dict(os.environ))
    reset_settings()


def _postgres_admin_url() -> str | None:
    return os.environ.get("BUS_TEST_POSTGRES_URL")


@pytest.fixture
def postgres_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """A throwaway PostgreSQL database (requires BUS_TEST_POSTGRES_URL with CREATEDB rights)."""
    admin = _postgres_admin_url()
    if not admin:
        pytest.skip("BUS_TEST_POSTGRES_URL is not set")
    import psycopg2

    name = f"bus_test_{uuid.uuid4().hex[:10]}"
    connection = psycopg2.connect(admin)
    connection.autocommit = True
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = admin.rpartition("/")
    url = f"{base}/{name}"
    for variable in CLEARED:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("BUS_BACKEND", "postgres")
    monkeypatch.setenv("BUS_POSTGRES_URL", url)
    monkeypatch.setenv("BUS_ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setenv("BUS_DBT_TARGET_DIR", str(tmp_path / "dbt-target"))
    monkeypatch.setenv("AT_SUB_KEY", "test-key")
    reset_settings()
    try:
        yield Settings.from_env(dict(os.environ))
    finally:
        reset_settings()
        with connection.cursor() as cursor:
            cursor.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        connection.close()


@pytest.fixture
def postgres_database() -> Iterator[str]:
    """An extra empty database URL, used as a remote publication target."""
    admin = _postgres_admin_url()
    if not admin:
        pytest.skip("BUS_TEST_POSTGRES_URL is not set")
    import psycopg2

    name = f"bus_remote_{uuid.uuid4().hex[:10]}"
    connection = psycopg2.connect(admin)
    connection.autocommit = True
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = admin.rpartition("/")
    try:
        yield f"{base}/{name}"
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        connection.close()
