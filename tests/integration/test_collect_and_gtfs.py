from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta

import pytest
from conftest import FIXTURES

from bus_checker.gtfs import GtfsValidationError, refresh_gtfs
from bus_checker.realtime import client
from bus_checker.realtime.client import Fetched, FetchError
from bus_checker.realtime.collector import collect, ingest_payload, replay
from bus_checker.warehouse import session

GTFS = str(FIXTURES / "gtfs")


def count(settings, sql: str) -> int:
    with session(settings, read_only=True) as wh:
        return int(wh.scalar(sql))


def test_ingest_is_idempotent_and_audited(duckdb_env, feed_bytes, now):
    payload = feed_bytes("trip_updates", now)
    first = ingest_payload(duckdb_env, "trip_updates", payload, now, source="api")
    assert (first.status, first.rows_inserted, first.rows_rejected) == ("warning", 6, 1)
    again = ingest_payload(duckdb_env, "trip_updates", payload, now, source="api")
    assert again.status == "unchanged"
    assert again.rows_inserted == 0
    replayed = ingest_payload(duckdb_env, "trip_updates", payload, now, source="replay", skip_unchanged=False)
    assert (replayed.rows_inserted, replayed.rows_duplicate) == (0, 6)
    later = now + timedelta(minutes=5)
    second = ingest_payload(
        duckdb_env, "trip_updates", feed_bytes("trip_updates", later, second=True), later, source="api"
    )
    assert second.rows_inserted == 2  # T2 reached a new stop; T4's prediction was refreshed
    assert count(duckdb_env, "SELECT count(*) FROM raw.trip_updates") == 8
    assert count(duckdb_env, "SELECT count(*) FROM ops.quarantine") == 3
    assert count(duckdb_env, "SELECT count(*) FROM ops.fetch_runs") == 4
    archived = list((duckdb_env.archive_dir / "trip_updates").rglob("*.json.gz"))
    assert len(archived) == 2  # unchanged and replayed payloads are not archived again


def test_failures_are_recorded_not_raised(duckdb_env, now):
    outcome = ingest_payload(duckdb_env, "vehicle_positions", b"{not json", now, source="api")
    assert outcome.failed
    assert "JSONDecodeError" in (outcome.error or "")
    with session(duckdb_env, read_only=True) as wh:
        status, error_type = wh.fetchall("SELECT status, error_type FROM ops.fetch_runs")[0]
    assert (status, error_type) == ("failed", "JSONDecodeError")
    assert count(duckdb_env, "SELECT count(*) FROM raw.vehicle_positions") == 0


def test_alert_versions_and_sightings(duckdb_env, feed_bytes, now):
    ingest_payload(duckdb_env, "service_alerts", feed_bytes("service_alerts", now), now, source="api")
    later = now + timedelta(minutes=5)
    ingest_payload(
        duckdb_env, "service_alerts", feed_bytes("service_alerts", now), later, source="replay", skip_unchanged=False
    )
    with session(duckdb_env, read_only=True) as wh:
        rows = wh.fetchall("SELECT alert_id, first_seen_at < last_seen_at FROM raw.service_alerts ORDER BY 1")
        entities = wh.scalar("SELECT count(*) FROM raw.service_alert_entities")
    assert rows == [("alert-detour", True), ("alert-future", True)]
    assert entities == 3


def test_collect_fetches_concurrently_and_isolates_failures(duckdb_env, feed_bytes, now, monkeypatch):
    def fake_fetch(session, settings, feed):
        if feed == "service_alerts":
            raise FetchError("HTTP 503 from service_alerts", 503)
        name = {"trip_updates": "trip_updates", "vehicle_positions": "vehicle_positions"}[feed]
        return Fetched(feed, feed_bytes(name, now), 200, datetime.now(UTC), 0.01)

    monkeypatch.setattr("bus_checker.realtime.collector.fetch_feed", fake_fetch)
    outcomes = {o.feed: o for o in collect(duckdb_env, run_id="test-run")}
    assert outcomes["trip_updates"].rows_inserted == 6
    assert outcomes["vehicle_positions"].rows_inserted == 5
    assert outcomes["service_alerts"].failed
    with session(duckdb_env, read_only=True) as wh:
        assert wh.fetchall("SELECT http_status FROM ops.fetch_runs WHERE status = 'failed'") == [(503,)]


def test_fetch_sends_key_and_rejects_errors(duckdb_env, monkeypatch):
    seen = {}

    class Response:
        status_code = 500

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def get(url, headers, timeout, stream):
        seen.update(headers)
        return Response()

    session_obj = client.make_session(duckdb_env)
    monkeypatch.setattr(session_obj, "get", get)
    with pytest.raises(FetchError) as error:
        client.fetch_feed(session_obj, duckdb_env, "trip_updates")
    assert error.value.status_code == 500
    assert seen["Ocp-Apim-Subscription-Key"] == "test-key"


def test_replay_archive_files(duckdb_env, feed_bytes, now, tmp_path):
    ingest_payload(duckdb_env, "vehicle_positions", feed_bytes("vehicle_positions", now), now, source="api")
    archive = duckdb_env.archive_dir
    copied = tmp_path / "copy"
    shutil.copytree(archive, copied)
    outcomes = replay(duckdb_env, [copied])
    assert [(o.feed, o.rows_inserted, o.rows_duplicate) for o in outcomes] == [("vehicle_positions", 0, 5)]


def test_gtfs_load_change_detection_and_rollback(duckdb_env, tmp_path):
    first = refresh_gtfs(duckdb_env, source=GTFS)
    assert first.status == "success"
    assert first.row_counts["gtfs_trips"] == 7
    assert first.feed_version == "fixture-1"
    assert refresh_gtfs(duckdb_env, source=GTFS).status == "unchanged"
    assert refresh_gtfs(duckdb_env, if_due=True).status == "skipped"
    with session(duckdb_env, read_only=True) as wh:
        pattern = wh.fetchall(
            "SELECT stop_id FROM raw.gtfs_route_stops WHERE route_id = '101-202' AND direction_id = 0 "
            "ORDER BY stop_order"
        )
        trip = wh.fetchall(
            "SELECT first_departure_sec, last_arrival_sec, stop_count FROM raw.gtfs_trips WHERE trip_id = 'T1'"
        )
    assert [p[0] for p in pattern] == ["1001-aaaa1111", "1002-bbbb2222", "1003-cccc3333"]
    assert trip == [(25200, 25800, 3)]

    broken = tmp_path / "broken"
    shutil.copytree(FIXTURES / "gtfs", broken)
    stops = (broken / "stops.txt").read_text(encoding="utf-8").splitlines()
    (broken / "stops.txt").write_text("\n".join([*stops, stops[1]]) + "\n", encoding="utf-8")
    with pytest.raises(GtfsValidationError, match="duplicate"):
        refresh_gtfs(duckdb_env, source=str(broken), force=True)
    assert count(duckdb_env, "SELECT count(*) FROM raw.gtfs_stops") == 6  # previous load intact
    with session(duckdb_env, read_only=True) as wh:
        statuses = [r[0] for r in wh.fetchall("SELECT status FROM ops.gtfs_loads ORDER BY started_at")]
    assert statuses == ["success", "unchanged", "failed"]
