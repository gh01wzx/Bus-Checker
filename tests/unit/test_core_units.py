from __future__ import annotations

import gzip
import os
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from bus_checker.config import ConfigError, Settings, normalise_postgres_url, postgres_parts
from bus_checker.dashboard.model import Filters
from bus_checker.dashboard.stats import histogram_quantiles, rollup, totals
from bus_checker.ids import stable_uuid
from bus_checker.publish.contract import ddl_type, pg_type
from bus_checker.realtime.archive import infer_feed, purge_archive, read_archive, received_time, write_archive
from bus_checker.warehouse import _csv_field, to_duckdb_sql, to_psycopg_sql


# ----------------------------------------------------------------------------- config
def test_settings_defaults_and_validation(tmp_path):
    settings = Settings.from_env({"BUS_ARCHIVE_DIR": "off"})
    assert settings.backend == "duckdb"
    assert settings.archive_dir is None
    assert settings.duckdb_path.name == "bus.duckdb"
    with pytest.raises(ConfigError):
        Settings.from_env({"BUS_BACKEND": "sqlite"})
    with pytest.raises(ConfigError):
        Settings.from_env({"BUS_PUBLISH_DAILY_DAYS": "0"})
    with pytest.raises(ConfigError):
        Settings.from_env({}).require_api_key()


def test_secrets_are_not_in_repr():
    settings = Settings.from_env({"AT_SUB_KEY": "very-secret", "BUS_POSTGRES_URL": "postgresql://u:pw@h/db"})
    assert "very-secret" not in repr(settings)
    assert "pw" not in repr(settings)


def test_postgres_urls():
    assert normalise_postgres_url("postgresql+psycopg2://u:p@h:5/d") == "postgresql://u:p@h:5/d"
    parts = postgres_parts("postgresql://bus%40x:p%2Fw@db.example:6543/postgres?sslmode=require", {})
    assert (parts.user, parts.password, parts.host, parts.port, parts.database, parts.sslmode) == (
        "bus@x",
        "p/w",
        "db.example",
        6543,
        "postgres",
        "require",
    )
    fallback = postgres_parts(None, {"PGHOST": "pg", "PGUSER": "w", "PGPASSWORD": "s", "PGDATABASE": "bus"})
    assert (fallback.host, fallback.user, fallback.database, fallback.port) == ("pg", "w", "bus", 5432)
    with pytest.raises(ConfigError):
        normalise_postgres_url("mysql://x")


# ----------------------------------------------------------------------------- SQL helpers
def test_parameter_translation():
    sql = "SELECT x::text, '%' FROM t WHERE a = :a AND b > :b_2"
    assert to_duckdb_sql(sql) == "SELECT x::text, '%' FROM t WHERE a = $a AND b > $b_2"
    assert to_psycopg_sql(sql, True) == "SELECT x::text, '%%' FROM t WHERE a = %(a)s AND b > %(b_2)s"
    assert to_psycopg_sql("SELECT '%'", False) == "SELECT '%'"


def test_csv_fields():
    assert _csv_field(None) == "\\N"
    assert _csv_field(True) == "t"
    assert _csv_field(float("nan")) == "\\N"
    assert _csv_field('a "quoted", value') == '"a ""quoted"", value"'
    assert _csv_field(date(2026, 1, 2)) == '"2026-01-02"'


def test_stable_uuid():
    assert stable_uuid("a", 1, None) == stable_uuid("a", 1, None)
    assert stable_uuid("a", 1) != stable_uuid("a", 2)


def test_type_mapping():
    assert pg_type("VARCHAR") == "text"
    assert pg_type("TIMESTAMP WITH TIME ZONE") == "timestamptz"
    assert pg_type("DECIMAL(18,3)") == "numeric"
    assert pg_type("character varying") == "text"
    assert ddl_type("duckdb", "double precision") == "DOUBLE"
    assert ddl_type("postgres", "double precision") == "double precision"


# ----------------------------------------------------------------------------- stats
def test_rates_are_weighted_by_counts():
    frame = pd.DataFrame(
        {
            "route": ["a", "a", "b"],
            "events": [10, 90, 1],
            "on_time": [10, 0, 1],
            "early": [0, 30, 0],
            "late": [0, 60, 0],
            "delay_sum_sec": [0, 9000, 0],
        }
    )
    rolled = rollup(frame, ["route"]).set_index("route")
    assert rolled.loc["a", "on_time_pct"] == 10  # 10 of 100, not the mean of 100% and 0%
    assert rolled.loc["a", "mean_delay_sec"] == 90
    summary = totals(frame)
    assert summary["events"] == 101
    assert round(summary["on_time_pct"], 3) == round(1100 / 101, 3)
    assert totals(frame.iloc[0:0])["on_time_pct"] is None


def test_histogram_quantiles():
    buckets = pd.Series([-1, 0, 1, 5])
    counts = pd.Series([25, 25, 25, 25])
    q = histogram_quantiles(buckets, counts, (0.5, 0.9))
    assert q[0.5] == pytest.approx(60.0)  # end of bucket 0
    assert 300 <= q[0.9] <= 360
    assert histogram_quantiles(pd.Series([], dtype=float), pd.Series([], dtype=float))[0.5] is None


def test_filters_bind_only_used_parameters():
    f = Filters(date(2026, 1, 1), date(2026, 1, 7), modes=("Bus",), day_types=("Weekday",))
    sql, params = f.where(route_column=None)
    assert "mode0" not in params
    assert ":mode0" not in sql
    sql, params = f.where("r")
    assert set(params) == {"start", "end", "mode0", "day0"}
    assert "r.route_key IN" in sql
    sql, params = Filters(date(2026, 1, 1), date(2026, 1, 1)).where()
    assert set(params) == {"start", "end"}
    assert f.previous() == Filters(date(2025, 12, 25), date(2025, 12, 31), ("Bus",), ("Weekday",))


# ----------------------------------------------------------------------------- archive
def test_archive_round_trip_and_purge(tmp_path):
    moment = datetime(2026, 7, 7, 8, 0, 5, tzinfo=UTC)
    path = write_archive(tmp_path, "trip_updates", moment, "abcdef1234567890", b'{"x": 1}')
    assert path.name == "20260707T080005Z-abcdef123456.json.gz"
    assert read_archive(path) == b'{"x": 1}'
    assert gzip.decompress(path.read_bytes()) == b'{"x": 1}'
    assert infer_feed(path) == "trip_updates"
    assert received_time(path) == moment
    old = datetime.now(UTC) - timedelta(days=30)
    os.utime(path, (old.timestamp(), old.timestamp()))
    assert purge_archive(tmp_path, 14) == 1
    assert not path.exists()
    assert purge_archive(tmp_path, 0) == 0
