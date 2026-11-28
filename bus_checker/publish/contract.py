"""The relations the dashboard reads. Snapshots and remote publications copy exactly these."""

from __future__ import annotations

from dataclasses import dataclass

MARTS_SCHEMA = "marts"
PUBLICATION_INFO = "publication_info"
PUBLICATION_LOG = "publication_log"


@dataclass(frozen=True)
class MartTable:
    name: str
    date_column: str | None = None
    # Retention class for remote publication: daily, hourly or detail. None = small table,
    # replaced in full on every publication.
    window: str | None = None


MARTS: tuple[MartTable, ...] = (
    MartTable("dim_routes"),
    MartTable("dim_stops"),
    MartTable("dim_route_stops"),
    MartTable("dim_route_shapes"),
    MartTable("dim_dates"),
    MartTable("network_daily", "service_date", "daily"),
    MartTable("network_hourly", "service_date", "hourly"),
    MartTable("route_daily", "service_date", "daily"),
    MartTable("route_hourly", "service_date", "hourly"),
    MartTable("route_delay_histogram", "service_date", "daily"),
    MartTable("stop_daily", "service_date", "detail"),
    MartTable("operator_daily", "service_date", "daily"),
    MartTable("service_delivery_hourly", "service_date", "hourly"),
    MartTable("cancelled_trips", "service_date", "detail"),
    MartTable("fleet_hourly", "service_date", "hourly"),
    MartTable("route_occupancy_daily", "service_date", "daily"),
    MartTable("live_vehicles"),
    MartTable("service_alerts"),
    MartTable("alert_routes"),
    MartTable("pipeline_feed_status"),
    MartTable("pipeline_fetch_runs"),
    MartTable("pipeline_daily_volume"),
    MartTable("pipeline_quarantine"),
    MartTable("pipeline_dbt_runs"),
    MartTable("pipeline_gtfs_loads"),
)

PUBLICATION_INFO_DDL = {
    "duckdb": (
        "publication_id VARCHAR, kind VARCHAR, source_backend VARCHAR, published_at TIMESTAMPTZ, "
        "data_through DATE, latest_ingested_at TIMESTAMPTZ"
    ),
    "postgres": (
        "publication_id text, kind text, source_backend text, published_at timestamptz, "
        "data_through date, latest_ingested_at timestamptz"
    ),
}


def pg_type(source_type: str) -> str:
    """Map a DuckDB or PostgreSQL ``information_schema`` type name to a PostgreSQL type."""
    t = source_type.strip().upper()
    if t.startswith(("VARCHAR", "CHARACTER VARYING", "TEXT", "CHAR")) or t == "STRING":
        return "text"
    mapping = {
        "BIGINT": "bigint",
        "INT8": "bigint",
        "INTEGER": "integer",
        "INT": "integer",
        "INT4": "integer",
        "SMALLINT": "smallint",
        "INT2": "smallint",
        "TINYINT": "smallint",
        "HUGEINT": "numeric",
        "DOUBLE": "double precision",
        "DOUBLE PRECISION": "double precision",
        "FLOAT8": "double precision",
        "FLOAT": "real",
        "REAL": "real",
        "FLOAT4": "real",
        "BOOLEAN": "boolean",
        "BOOL": "boolean",
        "DATE": "date",
        "TIMESTAMP WITH TIME ZONE": "timestamptz",
        "TIMESTAMPTZ": "timestamptz",
        "TIMESTAMP": "timestamp",
        "TIMESTAMP WITHOUT TIME ZONE": "timestamp",
        "UUID": "uuid",
        "INTERVAL": "interval",
    }
    if t in mapping:
        return mapping[t]
    if t.startswith(("DECIMAL", "NUMERIC")):
        return "numeric"
    return "text"


def ddl_type(kind: str, postgres_type: str) -> str:
    if kind == "postgres":
        return postgres_type
    return {
        "text": "VARCHAR",
        "double precision": "DOUBLE",
        "timestamptz": "TIMESTAMPTZ",
        "numeric": "DOUBLE",
        "real": "FLOAT",
    }.get(postgres_type, postgres_type.upper())
