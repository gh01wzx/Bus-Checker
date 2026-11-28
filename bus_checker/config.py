"""Runtime settings.

Every setting comes from an environment variable. A ``.env`` file in the repository root is
loaded first for native development; variables that are already set always win.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LOCAL_TZ = "Pacific/Auckland"
BACKENDS = ("duckdb", "postgres")

AT_REALTIME_BASE = "https://api.at.govt.nz/realtime/legacy"
DEFAULT_FEED_URLS = {
    "trip_updates": f"{AT_REALTIME_BASE}/tripupdates",
    "vehicle_positions": f"{AT_REALTIME_BASE}/vehiclelocations",
    "service_alerts": f"{AT_REALTIME_BASE}/servicealerts",
}
DEFAULT_GTFS_URL = "https://gtfs.at.govt.nz/gtfs.zip"


class ConfigError(ValueError):
    """Raised when the environment does not describe a usable configuration."""


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # The online dashboard does not need python-dotenv.
        return
    load_dotenv(ROOT / ".env", override=False)


def _int(env: Mapping[str, str], name: str, default: int, minimum: int = 0) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer") from None
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}")
    return value


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number") from None
    if value <= 0:
        raise ConfigError(f"{name} must be positive")
    return value


def _path(env: Mapping[str, str], name: str, default: str) -> Path:
    path = Path(env.get(name, "").strip() or default)
    return path if path.is_absolute() else (ROOT / path).resolve()


def _optional(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name, "").strip()
    return value or None


def normalise_postgres_url(url: str) -> str:
    """Accept SQLAlchemy-style URLs (``postgresql+psycopg2://``) as libpq URIs."""
    scheme, sep, rest = url.partition("://")
    if not sep:
        return url  # A libpq keyword/value DSN such as "host=... dbname=...".
    base = scheme.split("+", 1)[0]
    if base not in {"postgres", "postgresql"}:
        raise ConfigError("Postgres URLs must start with postgresql://")
    return f"postgresql://{rest}"


@dataclass(frozen=True)
class PostgresParts:
    host: str
    port: int
    user: str
    password: str = field(repr=False)
    database: str
    sslmode: str


def postgres_parts(url: str | None, env: Mapping[str, str]) -> PostgresParts:
    """Split a URL (or libpq PG* variables) into the fields dbt's profile needs."""
    if url and "://" in url:
        parts = urlsplit(normalise_postgres_url(url))
        query = dict(item.split("=", 1) for item in parts.query.split("&") if "=" in item)
        return PostgresParts(
            host=parts.hostname or "localhost",
            port=parts.port or 5432,
            user=unquote(parts.username or ""),
            password=unquote(parts.password or ""),
            database=(parts.path or "/").lstrip("/") or "postgres",
            sslmode=query.get("sslmode", env.get("PGSSLMODE", "prefer")),
        )
    return PostgresParts(
        host=env.get("PGHOST", "localhost"),
        port=int(env.get("PGPORT", "5432")),
        user=env.get("PGUSER", "bus_writer"),
        password=env.get("PGPASSWORD", ""),
        database=env.get("PGDATABASE", "bus"),
        sslmode=env.get("PGSSLMODE", "prefer"),
    )


@dataclass(frozen=True)
class Settings:
    backend: str
    duckdb_path: Path
    snapshot_path: Path
    postgres_url: str | None = field(repr=False)
    at_api_key: str | None = field(repr=False)
    feed_urls: Mapping[str, str]
    gtfs_url: str
    http_timeout: float
    archive_dir: Path | None
    archive_retention_days: int
    raw_retention_days: int
    ops_retention_days: int
    gtfs_refresh_hours: int
    publish_url: str | None = field(repr=False)
    publish_lookback_days: int
    publish_daily_days: int
    publish_hourly_days: int
    publish_detail_days: int
    dbt_project_dir: Path
    dbt_target_dir: Path
    lock_timeout: float

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        if env is None:
            _load_dotenv()
            env = os.environ
        backend = env.get("BUS_BACKEND", "duckdb").strip().lower() or "duckdb"
        if backend not in BACKENDS:
            raise ConfigError(f"BUS_BACKEND must be one of {', '.join(BACKENDS)}")
        archive = env.get("BUS_ARCHIVE_DIR", "").strip()
        return cls(
            backend=backend,
            duckdb_path=_path(env, "BUS_DUCKDB_PATH", "data/warehouse/bus.duckdb"),
            snapshot_path=_path(env, "BUS_SNAPSHOT_PATH", "data/published/bus_dashboard.duckdb"),
            postgres_url=_optional(env, "BUS_POSTGRES_URL"),
            at_api_key=_optional(env, "AT_SUB_KEY"),
            feed_urls={
                "trip_updates": env.get("AT_TRIP_UPDATES_URL") or DEFAULT_FEED_URLS["trip_updates"],
                "vehicle_positions": env.get("AT_VEHICLE_POSITIONS_URL") or DEFAULT_FEED_URLS["vehicle_positions"],
                "service_alerts": env.get("AT_SERVICE_ALERTS_URL") or DEFAULT_FEED_URLS["service_alerts"],
            },
            gtfs_url=env.get("AT_GTFS_URL") or DEFAULT_GTFS_URL,
            http_timeout=_float(env, "BUS_HTTP_TIMEOUT", 30.0),
            archive_dir=None
            if archive.lower() in {"off", "none", "disabled"}
            else _path(env, "BUS_ARCHIVE_DIR", "data/archive"),
            archive_retention_days=_int(env, "BUS_ARCHIVE_RETENTION_DAYS", 14),
            raw_retention_days=_int(env, "BUS_RAW_RETENTION_DAYS", 0),
            ops_retention_days=_int(env, "BUS_OPS_RETENTION_DAYS", 90, minimum=7),
            gtfs_refresh_hours=_int(env, "BUS_GTFS_REFRESH_HOURS", 24, minimum=1),
            publish_url=_optional(env, "BUS_PUBLISH_URL"),
            publish_lookback_days=_int(env, "BUS_PUBLISH_LOOKBACK_DAYS", 2, minimum=1),
            publish_daily_days=_int(env, "BUS_PUBLISH_DAILY_DAYS", 400, minimum=1),
            publish_hourly_days=_int(env, "BUS_PUBLISH_HOURLY_DAYS", 62, minimum=1),
            publish_detail_days=_int(env, "BUS_PUBLISH_DETAIL_DAYS", 31, minimum=1),
            dbt_project_dir=_path(env, "BUS_DBT_PROJECT_DIR", "bus_dbt"),
            dbt_target_dir=_path(env, "BUS_DBT_TARGET_DIR", "bus_dbt/target"),
            lock_timeout=_float(env, "BUS_LOCK_TIMEOUT", 60.0),
        )

    @property
    def postgres_dsn(self) -> str:
        """A libpq connection string. Empty means: use the PG* environment variables."""
        return normalise_postgres_url(self.postgres_url) if self.postgres_url else ""

    @property
    def warehouse_identity(self) -> str:
        if self.backend == "duckdb":
            return f"duckdb:{self.duckdb_path}"
        return f"postgres:{self.postgres_dsn or 'PG*'}"

    def require_api_key(self) -> str:
        if not self.at_api_key:
            raise ConfigError("AT_SUB_KEY is required for live collection")
        return self.at_api_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


def reset_settings() -> None:
    get_settings.cache_clear()
