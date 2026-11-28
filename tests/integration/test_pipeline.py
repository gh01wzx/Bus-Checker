"""End-to-end: collect -> GTFS -> dbt -> publish -> remote sync -> every dashboard page.

Runs on DuckDB always and on PostgreSQL when BUS_TEST_POSTGRES_URL is set.
"""

from __future__ import annotations

import os
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
import streamlit as st
from conftest import FIXTURES
from streamlit.testing.v1 import AppTest

from bus_checker.config import Settings, reset_settings
from bus_checker.gtfs import refresh_gtfs
from bus_checker.maintenance import maintain
from bus_checker.publish.remote import sync_remote
from bus_checker.publish.snapshot import publish_snapshot
from bus_checker.realtime.collector import ingest_payload
from bus_checker.transform import build
from bus_checker.warehouse import open_url, session

PAGES = [
    "overview",
    "live",
    "alerts",
    "routes",
    "compare",
    "patterns",
    "stops",
    "operators",
    "delivery",
    "fleet",
    "health",
    "about",
]
pytestmark = pytest.mark.integration


def load_snapshot(settings: Settings, feed_bytes, moment, second: bool = False) -> None:
    kwargs = {"second": True} if second else {}
    for feed in ("trip_updates", "vehicle_positions", "service_alerts"):
        extra = kwargs if feed == "trip_updates" else {}
        outcome = ingest_payload(settings, feed, feed_bytes(feed, moment, **extra), moment, source="api")
        assert not outcome.failed, outcome.error


def marts(settings: Settings, sql: str):
    with session(settings, read_only=True) as wh:
        return wh.frame(sql)


def run_pipeline(settings: Settings, feed_bytes, now, tmp_path, remote_url: str) -> None:
    load_snapshot(settings, feed_bytes, now)
    refresh_gtfs(settings, source=str(FIXTURES / "gtfs"))
    summary = build(settings, full_tests=True)
    assert summary.status == "success"
    assert summary.tests_fail == 0
    assert summary.tests_pass > 40

    daily = marts(settings, "SELECT * FROM marts.network_daily").set_index("mode")
    bus, train = daily.loc["Bus"], daily.loc["Train"]
    assert (bus.events, bus.on_time, bus.early, bus.late) == (3, 1, 1, 1)  # T4 prediction excluded
    assert (train.events, train.on_time) == (1, 1)
    assert bus.trips_cancelled == 1
    assert bus.trips_tracked == 3
    weekday = now.astimezone(ZoneInfo("Pacific/Auckland")).isoweekday() <= 5
    assert bus.trips_scheduled == 5 + (1 if weekday else 0)

    routes = marts(settings, "SELECT route_key, mode, operator_name, route_label FROM marts.dim_routes").set_index(
        "route_key"
    )
    assert routes.loc["101", "route_label"] == "101 · Point Chevalier"
    assert routes.loc["WEST", "mode"] == "Train"
    live = marts(settings, "SELECT * FROM marts.live_vehicles").set_index("vehicle_id")
    assert set(live.index) == {"V1", "V2", "V3", "V9"}  # V10 is outside Auckland
    assert live.loc["V2", "punctuality"] == "late"
    assert not live.loc["V9", "in_service"]
    alerts = marts(settings, "SELECT alert_id, is_active FROM marts.service_alerts").set_index("alert_id")
    assert bool(alerts.loc["alert-detour", "is_active"])
    assert not bool(alerts.loc["alert-future", "is_active"])
    assert len(marts(settings, "SELECT * FROM marts.alert_routes WHERE route_key = '101'")) == 1

    # Second collection five minutes later: one new stop event, nothing double counted.
    later = now + timedelta(minutes=5)
    load_snapshot(settings, feed_bytes, later, second=True)
    build(settings, full_tests=True)
    events = marts(settings, "SELECT sum(events) AS n FROM marts.route_daily").iloc[0]["n"]
    assert events == 5
    t2 = marts(settings, "SELECT report_count, stops_observed FROM core.fct_trips WHERE trip_id = 'T2'").iloc[0]
    assert t2["stops_observed"] == 2

    if settings.backend == "duckdb":
        result = publish_snapshot(settings)
        assert result["tables"]["route_daily"] > 0

    first = sync_remote(settings)
    assert first["rows_copied"] > 0
    again = sync_remote(settings)
    assert again["tables"]["dim_route_shapes"].get("unchanged") is True
    target = open_url(remote_url, read_only=True)
    try:
        assert target.scalar("SELECT sum(events) FROM marts.route_daily") == 5
        assert target.scalar("SELECT count(*) FROM marts.publication_log") == 2
        assert target.scalar("SELECT kind FROM marts.publication_info") == "remote"
    finally:
        target.close()

    report = maintain(settings)
    assert "vacuum" in report


def check_dashboard() -> None:
    st.cache_data.clear()
    st.cache_resource.clear()
    reset_settings()
    for page in PAGES:
        script = (
            f"from bus_checker.dashboard.views import {page}\n"
            "from bus_checker.dashboard.ui import guarded\n"
            f"guarded({page}.render)()"
        )
        app = AppTest.from_string(script, default_timeout=60).run()
        assert not app.exception, (page, [e.value for e in app.exception])
        assert not app.error, (page, [e.value for e in app.error])
        if page not in ("about",):
            assert len(app.get("plotly_chart")) + len(app.metric) > 0, page
    app = AppTest.from_file("streamlit_app.py", default_timeout=60).run()
    assert not app.exception


def test_pipeline_duckdb(duckdb_env, feed_bytes, now, tmp_path, monkeypatch):
    remote = tmp_path / "remote.duckdb"
    monkeypatch.setenv("BUS_PUBLISH_URL", str(remote))
    settings = Settings.from_env(dict(os.environ))
    run_pipeline(settings, feed_bytes, now, tmp_path, str(remote))
    check_dashboard()


@pytest.mark.postgres
def test_pipeline_postgres(postgres_env, postgres_database, feed_bytes, now, tmp_path, monkeypatch):
    monkeypatch.setenv("BUS_PUBLISH_URL", postgres_database)
    settings = Settings.from_env(dict(os.environ))
    run_pipeline(settings, feed_bytes, now, tmp_path, postgres_database)
    # The online dashboard reads the remote publication exactly as Streamlit Cloud would.
    monkeypatch.setenv("BUS_POSTGRES_URL", postgres_database)
    check_dashboard()
