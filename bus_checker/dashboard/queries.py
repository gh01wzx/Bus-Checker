"""Every SQL statement the dashboard runs. All of them read the ``marts`` schema only and
aggregate in the database, so the online deployment transfers small result sets."""

from __future__ import annotations

from datetime import date

import pandas as pd

from bus_checker.dashboard.data import DataUnavailable, in_list, query
from bus_checker.dashboard.model import Filters

COUNTS = (
    "CAST(sum(events) AS BIGINT) AS events, CAST(sum(on_time) AS BIGINT) AS on_time, "
    "CAST(sum(early) AS BIGINT) AS early, CAST(sum(late) AS BIGINT) AS late, "
    "CAST(sum(delay_sum_sec) AS BIGINT) AS delay_sum_sec"
)


# ----------------------------------------------------------------------------- metadata
def date_bounds() -> tuple[date, date] | None:
    frame = query(
        "SELECT min(service_date) AS first_date, max(service_date) AS last_date "
        "FROM marts.network_daily WHERE events > 0"
    )
    if frame.empty or pd.isna(frame.iloc[0]["first_date"]):
        return None
    row = frame.iloc[0]
    return pd.Timestamp(row["first_date"]).date(), pd.Timestamp(row["last_date"]).date()


def modes() -> list[str]:
    frame = query(
        "SELECT mode, sum(events) AS events FROM marts.network_daily WHERE events > 0 GROUP BY mode ORDER BY 2 DESC"
    )
    return frame["mode"].tolist()


def publication_info() -> pd.Series | None:
    try:
        frame = query("SELECT * FROM marts.publication_info")
    except DataUnavailable:
        return None  # Local PostgreSQL reads marts directly; there is no publication step.
    return None if frame.empty else frame.iloc[0]


def routes() -> pd.DataFrame:
    return query("SELECT * FROM marts.dim_routes ORDER BY route_short_name")


# ----------------------------------------------------------------------------- network
def network_daily(filters: Filters) -> pd.DataFrame:
    where, params = filters.where(route_column=None, mode_column="mode")
    return query(f"SELECT * FROM marts.network_daily WHERE {where} ORDER BY service_date", params)


def network_hourly(filters: Filters) -> pd.DataFrame:
    where, params = filters.where(route_column=None, mode_column="mode")
    return query(
        f"SELECT service_date, day_type, hour, {COUNTS} FROM marts.network_hourly "
        f"WHERE {where} GROUP BY service_date, day_type, hour",
        params,
    )


def network_histogram(filters: Filters) -> pd.DataFrame:
    where, params = filters.where()
    return query(
        "SELECT delay_bucket_min, CAST(sum(events) AS BIGINT) AS events "
        f"FROM marts.route_delay_histogram WHERE {where} GROUP BY delay_bucket_min",
        params,
    )


# ----------------------------------------------------------------------------- routes
def route_totals(filters: Filters) -> pd.DataFrame:
    where, params = filters.where("d")
    return query(
        "SELECT d.route_key, "
        "CAST(sum(d.events) AS BIGINT) AS events, CAST(sum(d.on_time) AS BIGINT) AS on_time, "
        "CAST(sum(d.early) AS BIGINT) AS early, CAST(sum(d.late) AS BIGINT) AS late, "
        "CAST(sum(d.delay_sum_sec) AS BIGINT) AS delay_sum_sec, "
        "sum(d.delay_sq_sum) AS delay_sq_sum, max(d.delay_max_sec) AS delay_max_sec, "
        "CAST(sum(d.trips_tracked) AS BIGINT) AS trips_tracked, "
        "CAST(sum(d.trips_scheduled) AS BIGINT) AS trips_scheduled, "
        "CAST(sum(d.trips_cancelled) AS BIGINT) AS trips_cancelled, "
        "CAST(sum(d.vehicles) AS BIGINT) AS vehicle_days, "
        "count(DISTINCT d.service_date) AS active_days "
        f"FROM marts.route_daily AS d WHERE {where} GROUP BY d.route_key",
        params,
    )


def route_daily(filters: Filters, route_keys: list[str]) -> pd.DataFrame:
    where, params = filters.where()
    slots, values = in_list("rk", route_keys)
    return query(
        f"SELECT * FROM marts.route_daily WHERE {where} AND route_key IN {slots} ORDER BY service_date",
        params | values,
    )


def route_hourly(filters: Filters, route_keys: list[str]) -> pd.DataFrame:
    where, params = filters.where()
    slots, values = in_list("rk", route_keys)
    return query(
        f"SELECT route_key, direction_id, day_type, hour, {COUNTS} FROM marts.route_hourly "
        f"WHERE {where} AND route_key IN {slots} GROUP BY route_key, direction_id, day_type, hour",
        params | values,
    )


def route_histogram(filters: Filters, route_keys: list[str]) -> pd.DataFrame:
    where, params = filters.where()
    slots, values = in_list("rk", route_keys)
    return query(
        "SELECT route_key, delay_bucket_min, CAST(sum(events) AS BIGINT) AS events "
        f"FROM marts.route_delay_histogram WHERE {where} AND route_key IN {slots} "
        "GROUP BY route_key, delay_bucket_min",
        params | values,
    )


def route_stop_profile(filters: Filters, route_key: str) -> pd.DataFrame:
    where, params = filters.where("s", route_column=None)
    return query(
        "SELECT p.direction_id, p.stop_order, p.stop_key, p.stop_name, p.latitude, p.longitude, "
        "CAST(coalesce(sum(s.events), 0) AS BIGINT) AS events, "
        "CAST(coalesce(sum(s.on_time), 0) AS BIGINT) AS on_time, "
        "CAST(coalesce(sum(s.early), 0) AS BIGINT) AS early, "
        "CAST(coalesce(sum(s.late), 0) AS BIGINT) AS late, "
        "CAST(coalesce(sum(s.delay_sum_sec), 0) AS BIGINT) AS delay_sum_sec "
        "FROM marts.dim_route_stops AS p "
        "LEFT JOIN marts.stop_daily AS s ON s.route_key = p.route_key "
        f"AND s.direction_id = p.direction_id AND s.stop_key = p.stop_key AND {where} "
        "WHERE p.route_key = :route "
        "GROUP BY p.direction_id, p.stop_order, p.stop_key, p.stop_name, p.latitude, p.longitude "
        "ORDER BY p.direction_id, p.stop_order",
        params | {"route": route_key},
    )


def route_shape(route_key: str) -> pd.DataFrame:
    return query(
        "SELECT direction_id, point_order, latitude, longitude FROM marts.dim_route_shapes "
        "WHERE route_key = :route ORDER BY direction_id, point_order",
        {"route": route_key},
    )


def route_alerts(route_key: str) -> pd.DataFrame:
    return query(
        "SELECT DISTINCT a.alert_id, a.effect, a.severity, a.header_text, a.is_active "
        "FROM marts.alert_routes AS a WHERE a.route_key = :route ORDER BY a.is_active DESC",
        {"route": route_key},
    )


def cancelled_trips(filters: Filters, route_key: str | None = None, limit: int = 1000) -> pd.DataFrame:
    where, params = filters.where("c")
    extra = ""
    if route_key:
        extra = " AND c.route_key = :route"
        params["route"] = route_key
    return query(
        "SELECT c.service_date, c.route_key, r.route_short_name, c.direction_id, c.start_time, "
        "c.trip_headsign, c.first_seen_at, c.trip_id FROM marts.cancelled_trips AS c "
        "LEFT JOIN marts.dim_routes AS r ON r.route_key = c.route_key "
        f"WHERE {where}{extra} ORDER BY c.service_date DESC, c.start_time LIMIT {int(limit)}",
        params,
    )


# ----------------------------------------------------------------------------- stops
def stop_totals(filters: Filters, route_key: str | None = None) -> pd.DataFrame:
    where, params = filters.where("s")
    extra = ""
    if route_key:
        extra = " AND s.route_key = :route"
        params["route"] = route_key
    return query(
        "SELECT s.stop_key, d.stop_name, d.latitude, d.longitude, "
        "CAST(sum(s.events) AS BIGINT) AS events, CAST(sum(s.on_time) AS BIGINT) AS on_time, "
        "CAST(sum(s.early) AS BIGINT) AS early, CAST(sum(s.late) AS BIGINT) AS late, "
        "CAST(sum(s.delay_sum_sec) AS BIGINT) AS delay_sum_sec, "
        "count(DISTINCT s.route_key) AS routes "
        "FROM marts.stop_daily AS s LEFT JOIN marts.dim_stops AS d ON d.stop_key = s.stop_key "
        f"WHERE {where}{extra} GROUP BY s.stop_key, d.stop_name, d.latitude, d.longitude",
        params,
    )


def stop_detail(filters: Filters, stop_key: str) -> pd.DataFrame:
    where, params = filters.where("s")
    return query(
        "SELECT s.service_date, s.route_key, r.route_short_name, s.direction_id, "
        "s.events, s.on_time, s.early, s.late, s.delay_sum_sec FROM marts.stop_daily AS s "
        "LEFT JOIN marts.dim_routes AS r ON r.route_key = s.route_key "
        f"WHERE {where} AND s.stop_key = :stop",
        params | {"stop": stop_key},
    )


# ----------------------------------------------------------------------------- operations
def operator_daily(filters: Filters) -> pd.DataFrame:
    where, params = filters.where(route_column=None, mode_column="mode")
    return query(f"SELECT * FROM marts.operator_daily WHERE {where}", params)


def service_delivery_hourly(filters: Filters) -> pd.DataFrame:
    where, params = filters.where()
    return query(
        "SELECT start_hour, day_type, CAST(sum(trips_scheduled) AS BIGINT) AS trips_scheduled, "
        "CAST(sum(trips_tracked) AS BIGINT) AS trips_tracked, "
        "CAST(sum(trips_cancelled) AS BIGINT) AS trips_cancelled, "
        "count(DISTINCT service_date) AS days "
        f"FROM marts.service_delivery_hourly WHERE {where} GROUP BY start_hour, day_type",
        params,
    )


def fleet_hourly(filters: Filters) -> pd.DataFrame:
    where, params = filters.where(route_column=None)
    return query(f"SELECT * FROM marts.fleet_hourly WHERE {where}", params)


def route_occupancy(filters: Filters) -> pd.DataFrame:
    where, params = filters.where()
    return query(
        "SELECT route_key, occupancy_status, CAST(sum(reports) AS BIGINT) AS reports "
        f"FROM marts.route_occupancy_daily WHERE {where} GROUP BY route_key, occupancy_status",
        params,
    )


# ----------------------------------------------------------------------------- live
def live_vehicles() -> pd.DataFrame:
    return query("SELECT * FROM marts.live_vehicles")


def service_alerts() -> pd.DataFrame:
    return query("SELECT * FROM marts.service_alerts ORDER BY last_seen_at DESC")


# ----------------------------------------------------------------------------- pipeline
def pipeline(table: str) -> pd.DataFrame:
    allowed = {
        "pipeline_feed_status",
        "pipeline_fetch_runs",
        "pipeline_daily_volume",
        "pipeline_quarantine",
        "pipeline_dbt_runs",
        "pipeline_gtfs_loads",
    }
    if table not in allowed:
        raise ValueError(table)
    return query(f"SELECT * FROM marts.{table}")
