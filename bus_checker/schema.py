"""Tables owned by Python: immutable raw facts, GTFS reference data and operational audit.

dbt owns everything in the ``staging``, ``core`` and ``marts`` schemas. This module is the
single source of truth for the DDL below; the loaders build their rows from the same
column lists, so the two cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bus_checker.config import Settings
from bus_checker.warehouse import Column, Warehouse, qualified, quote_identifier

SCHEMA_VERSION = "2"
PYTHON_SCHEMAS = ("raw", "ops")


@dataclass(frozen=True)
class Table:
    schema: str
    name: str
    columns: tuple[Column, ...]
    primary_key: tuple[str, ...] = ()
    # Large append-only tables skip the DuckDB primary key: its ART index would have to cover
    # every row, while loaders already de-duplicate against a bounded date range.
    duckdb_primary_key: bool = True
    indexes: tuple[tuple[str, ...], ...] = field(default=())

    @property
    def ref(self) -> str:
        return qualified(self.schema, self.name)

    @property
    def column_names(self) -> list[str]:
        return [column.name for column in self.columns]

    def ddl(self, kind: str) -> str:
        parts = []
        for column in self.columns:
            sql_type = column_type(column, kind)
            null = "" if column.nullable else " NOT NULL"
            parts.append(f"{quote_identifier(column.name)} {sql_type}{null}")
        if self.primary_key and (kind == "postgres" or self.duckdb_primary_key):
            keys = ", ".join(quote_identifier(k) for k in self.primary_key)
            parts.append(f"PRIMARY KEY ({keys})")
        return f"CREATE TABLE IF NOT EXISTS {self.ref} (\n    " + ",\n    ".join(parts) + "\n)"


def column_type(column: Column, kind: str) -> str:
    from bus_checker.warehouse import SQL_TYPES

    duck, pg = SQL_TYPES[column.type]
    return duck if kind == "duckdb" else pg


def C(name: str, type_: str, nullable: bool = True) -> Column:
    return Column(name, type_, nullable)


# --------------------------------------------------------------------------------------
# Realtime facts
# --------------------------------------------------------------------------------------
TRIP_UPDATES = Table(
    "raw",
    "trip_updates",
    (
        C("update_id", "uuid", False),
        C("fetch_id", "uuid", False),
        C("ingested_at", "timestamptz", False),
        C("feed_ts", "timestamptz", False),
        C("service_date", "date", False),
        C("entity_id", "text"),
        C("trip_id", "text", False),
        C("route_id", "text"),
        C("direction_id", "smallint"),
        C("start_time", "text"),
        C("trip_schedule_relationship", "text"),
        C("vehicle_id", "text"),
        C("vehicle_label", "text"),
        C("update_ts", "timestamptz"),
        C("trip_delay_sec", "int"),
        C("stop_id", "text"),
        C("stop_sequence", "int"),
        C("stop_schedule_relationship", "text"),
        C("arrival_delay_sec", "int"),
        C("arrival_ts", "timestamptz"),
        C("arrival_uncertainty_sec", "int"),
        C("departure_delay_sec", "int"),
        C("departure_ts", "timestamptz"),
    ),
    primary_key=("update_id",),
    duckdb_primary_key=False,
    indexes=(("service_date",), ("ingested_at",)),
)

VEHICLE_POSITIONS = Table(
    "raw",
    "vehicle_positions",
    (
        C("position_id", "uuid", False),
        C("fetch_id", "uuid", False),
        C("ingested_at", "timestamptz", False),
        C("feed_ts", "timestamptz", False),
        C("position_ts", "timestamptz", False),
        C("service_date", "date", False),
        C("entity_id", "text"),
        C("vehicle_id", "text", False),
        C("vehicle_label", "text"),
        C("license_plate", "text"),
        C("trip_id", "text"),
        C("route_id", "text"),
        C("direction_id", "smallint"),
        C("start_time", "text"),
        C("trip_schedule_relationship", "text"),
        C("latitude", "double", False),
        C("longitude", "double", False),
        C("bearing", "double"),
        C("speed_kmh", "double"),
        C("odometer_m", "double"),
        C("occupancy_status", "text"),
    ),
    primary_key=("position_id",),
    duckdb_primary_key=False,
    indexes=(("service_date",), ("ingested_at",)),
)

SERVICE_ALERTS = Table(
    "raw",
    "service_alerts",
    (
        C("alert_version_id", "uuid", False),
        C("alert_id", "text", False),
        C("cause", "text"),
        C("effect", "text"),
        C("severity", "text"),
        C("header_text", "text"),
        C("description_text", "text"),
        C("effect_detail", "text"),
        C("url", "text"),
        C("active_periods", "text"),
        C("period_start", "timestamptz"),
        C("period_end", "timestamptz"),
        C("informed_entity_count", "int"),
        C("first_seen_at", "timestamptz", False),
        C("last_seen_at", "timestamptz", False),
        C("last_fetch_id", "uuid", False),
        C("active_at_last_seen", "bool", False),
    ),
    primary_key=("alert_version_id",),
    indexes=(("last_seen_at",),),
)

SERVICE_ALERT_ENTITIES = Table(
    "raw",
    "service_alert_entities",
    (
        C("alert_version_id", "uuid", False),
        C("entity_index", "int", False),
        C("route_id", "text"),
        C("stop_id", "text"),
        C("trip_id", "text"),
        C("direction_id", "smallint"),
    ),
    primary_key=("alert_version_id", "entity_index"),
)

# --------------------------------------------------------------------------------------
# GTFS static reference (replaced atomically on refresh)
# --------------------------------------------------------------------------------------
GTFS_AGENCY = Table(
    "raw",
    "gtfs_agency",
    (C("agency_id", "text", False), C("agency_name", "text"), C("agency_url", "text")),
    primary_key=("agency_id",),
)
GTFS_ROUTES = Table(
    "raw",
    "gtfs_routes",
    (
        C("route_id", "text", False),
        C("agency_id", "text"),
        C("route_short_name", "text"),
        C("route_long_name", "text"),
        C("route_type", "int"),
        C("route_color", "text"),
        C("route_text_color", "text"),
    ),
    primary_key=("route_id",),
)
GTFS_TRIPS = Table(
    "raw",
    "gtfs_trips",
    (
        C("trip_id", "text", False),
        C("route_id", "text", False),
        C("service_id", "text", False),
        C("trip_headsign", "text"),
        C("direction_id", "smallint"),
        C("shape_id", "text"),
        C("first_departure_sec", "int"),
        C("last_arrival_sec", "int"),
        C("stop_count", "int"),
        C("first_stop_id", "text"),
        C("last_stop_id", "text"),
    ),
    primary_key=("trip_id",),
)
GTFS_STOPS = Table(
    "raw",
    "gtfs_stops",
    (
        C("stop_id", "text", False),
        C("stop_code", "text"),
        C("stop_name", "text"),
        C("stop_lat", "double"),
        C("stop_lon", "double"),
        C("location_type", "smallint"),
        C("parent_station", "text"),
    ),
    primary_key=("stop_id",),
)
GTFS_CALENDAR = Table(
    "raw",
    "gtfs_calendar",
    (
        C("service_id", "text", False),
        C("monday", "bool", False),
        C("tuesday", "bool", False),
        C("wednesday", "bool", False),
        C("thursday", "bool", False),
        C("friday", "bool", False),
        C("saturday", "bool", False),
        C("sunday", "bool", False),
        C("start_date", "date", False),
        C("end_date", "date", False),
    ),
    primary_key=("service_id",),
)
GTFS_CALENDAR_DATES = Table(
    "raw",
    "gtfs_calendar_dates",
    (
        C("service_id", "text", False),
        C("service_date", "date", False),
        C("exception_type", "smallint", False),
    ),
    primary_key=("service_id", "service_date"),
)
GTFS_ROUTE_STOPS = Table(
    "raw",
    "gtfs_route_stops",
    (
        C("route_id", "text", False),
        C("direction_id", "smallint", False),
        C("stop_order", "int", False),
        C("stop_id", "text", False),
        C("pattern_trip_count", "int", False),
    ),
    primary_key=("route_id", "direction_id", "stop_order"),
)
GTFS_ROUTE_SHAPES = Table(
    "raw",
    "gtfs_route_shapes",
    (
        C("route_id", "text", False),
        C("direction_id", "smallint", False),
        C("shape_id", "text", False),
        C("point_order", "int", False),
        C("latitude", "double", False),
        C("longitude", "double", False),
    ),
    primary_key=("route_id", "direction_id", "point_order"),
)
GTFS_TABLES = (
    GTFS_AGENCY,
    GTFS_ROUTES,
    GTFS_TRIPS,
    GTFS_STOPS,
    GTFS_CALENDAR,
    GTFS_CALENDAR_DATES,
    GTFS_ROUTE_STOPS,
    GTFS_ROUTE_SHAPES,
)

# --------------------------------------------------------------------------------------
# Operational audit
# --------------------------------------------------------------------------------------
FETCH_RUNS = Table(
    "ops",
    "fetch_runs",
    (
        C("fetch_id", "uuid", False),
        C("run_id", "text"),
        C("feed", "text", False),
        C("source", "text", False),
        C("started_at", "timestamptz", False),
        C("finished_at", "timestamptz", False),
        C("status", "text", False),
        C("http_status", "int"),
        C("feed_ts", "timestamptz"),
        C("entity_count", "int"),
        C("rows_parsed", "int"),
        C("rows_inserted", "int"),
        C("rows_duplicate", "int"),
        C("rows_rejected", "int"),
        C("payload_bytes", "bigint"),
        C("payload_sha256", "text"),
        C("archive_path", "text"),
        C("error_type", "text"),
        C("error_message", "text"),
    ),
    primary_key=("fetch_id",),
    indexes=(("started_at",), ("feed", "started_at")),
)
QUARANTINE = Table(
    "ops",
    "quarantine",
    (
        C("rejection_id", "uuid", False),
        C("fetch_id", "uuid", False),
        C("feed", "text", False),
        C("reason", "text", False),
        C("record", "text"),
        C("created_at", "timestamptz", False),
    ),
    primary_key=("rejection_id",),
    indexes=(("created_at",),),
)
GTFS_LOADS = Table(
    "ops",
    "gtfs_loads",
    (
        C("load_id", "uuid", False),
        C("started_at", "timestamptz", False),
        C("finished_at", "timestamptz", False),
        C("status", "text", False),
        C("source", "text"),
        C("sha256", "text"),
        C("etag", "text"),
        C("last_modified", "text"),
        C("feed_version", "text"),
        C("feed_start_date", "date"),
        C("feed_end_date", "date"),
        C("row_counts", "text"),
        C("error_message", "text"),
    ),
    primary_key=("load_id",),
)
DBT_RUNS = Table(
    "ops",
    "dbt_runs",
    (
        C("invocation_id", "text", False),
        C("command", "text", False),
        C("started_at", "timestamptz", False),
        C("finished_at", "timestamptz", False),
        C("elapsed_sec", "double"),
        C("status", "text", False),
        C("models_ok", "int"),
        C("models_error", "int"),
        C("tests_pass", "int"),
        C("tests_fail", "int"),
        C("tests_warn", "int"),
        C("skipped", "int"),
        C("failures", "text"),
    ),
    primary_key=("invocation_id",),
)
PUBLICATIONS = Table(
    "ops",
    "publications",
    (
        C("publication_id", "uuid", False),
        C("target", "text", False),
        C("started_at", "timestamptz", False),
        C("finished_at", "timestamptz", False),
        C("status", "text", False),
        C("details", "text"),
        C("error_message", "text"),
    ),
    primary_key=("publication_id",),
)
SCHEMA_INFO = Table(
    "ops",
    "schema_info",
    (C("key", "text", False), C("value", "text", False)),
    primary_key=("key",),
)

ALL_TABLES = (
    TRIP_UPDATES,
    VEHICLE_POSITIONS,
    SERVICE_ALERTS,
    SERVICE_ALERT_ENTITIES,
    *GTFS_TABLES,
    FETCH_RUNS,
    QUARANTINE,
    GTFS_LOADS,
    DBT_RUNS,
    PUBLICATIONS,
    SCHEMA_INFO,
)


class SchemaVersionError(RuntimeError):
    pass


_READY: set[str] = set()


def ensure_ready(settings: Settings) -> None:
    """Create the schema in its own committed transaction, at most once per process.

    Keeping DDL out of the loading transaction matters: a failed load rolls back, and on
    DuckDB that would also roll back tables created in the same transaction.
    """
    from bus_checker.warehouse import session

    identity = settings.warehouse_identity
    if identity in _READY:
        return
    with session(settings) as warehouse:
        ensure_schema(warehouse)
    _READY.add(identity)


def ensure_schema(warehouse: Warehouse) -> None:
    """Create missing schemas, tables and indexes. Safe to call on every run."""
    for schema in PYTHON_SCHEMAS:
        warehouse.execute(f"CREATE SCHEMA IF NOT EXISTS {quote_identifier(schema)}")
    for table in ALL_TABLES:
        warehouse.execute(table.ddl(warehouse.kind))
        if warehouse.kind == "postgres":
            for columns in table.indexes:
                name = f"ix_{table.name}_{'_'.join(columns)}"
                cols = ", ".join(quote_identifier(c) for c in columns)
                warehouse.execute(f"CREATE INDEX IF NOT EXISTS {quote_identifier(name)} ON {table.ref} ({cols})")
    version = warehouse.scalar(f"SELECT value FROM {SCHEMA_INFO.ref} WHERE key = 'schema_version'")
    if version is None:
        warehouse.execute(
            f"INSERT INTO {SCHEMA_INFO.ref} (key, value) VALUES ('schema_version', :v)",
            {"v": SCHEMA_VERSION},
        )
    elif version != SCHEMA_VERSION:
        raise SchemaVersionError(
            f"Warehouse schema version {version} does not match {SCHEMA_VERSION}. "
            "Point BUS_DUCKDB_PATH / BUS_POSTGRES_URL at a new warehouse."
        )
