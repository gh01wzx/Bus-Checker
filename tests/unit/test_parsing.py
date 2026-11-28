from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import feeds
import pytest

from bus_checker.realtime.parsing import (
    FeedError,
    enum_name,
    epoch,
    parse_service_alerts,
    parse_trip_updates,
    parse_vehicle_positions,
    translated,
)

NOW = datetime(2026, 7, 7, 8, 0, tzinfo=UTC)


def by_trip(rows):
    return {row["trip_id"]: row for row in rows}


def test_trip_updates_classify_and_quarantine():
    parsed = parse_trip_updates(feeds.trip_updates(NOW), NOW)
    rows = by_trip(parsed.rows)
    assert parsed.entity_count == 7
    assert set(rows) == {"T1", "T2", "T3", "T4", "T5", "T6"}
    assert [reason for reason, _ in parsed.rejects] == ["missing_trip_id"]
    assert rows["T1"]["arrival_delay_sec"] == 90
    assert rows["T1"]["vehicle_label"] == "NB 101"  # whitespace collapsed
    assert rows["T3"]["arrival_delay_sec"] is None
    assert rows["T3"]["departure_delay_sec"] == -120
    assert rows["T5"]["trip_schedule_relationship"] == "CANCELED"
    assert rows["T5"]["stop_id"] is None
    assert rows["T1"]["service_date"].isoformat() == "2026-07-07"
    assert rows["T1"]["feed_ts"] == NOW


def test_identical_reports_get_identical_ids_across_snapshots():
    first = by_trip(parse_trip_updates(feeds.trip_updates(NOW), NOW).rows)
    later = NOW + timedelta(minutes=5)
    second = by_trip(parse_trip_updates(feeds.trip_updates(later, second=True), later).rows)
    assert first["T1"]["update_id"] == second["T1"]["update_id"]
    assert first["T2"]["update_id"] != second["T2"]["update_id"]


def test_entity_order_and_duplicates_do_not_change_rows():
    payload = feeds.trip_updates(NOW)
    reordered = copy.deepcopy(payload)
    reordered["response"]["entity"].reverse()
    a = parse_trip_updates(payload, NOW)
    b = parse_trip_updates(reordered, NOW)
    assert {r["update_id"] for r in a.rows} == {r["update_id"] for r in b.rows}
    doubled = copy.deepcopy(payload)
    doubled["response"]["entity"] *= 2
    c = parse_trip_updates(doubled, NOW)
    assert len(c.rows) == len(a.rows)
    assert c.duplicates == len(a.rows)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda u: u["trip"].update(direction_id=7), "invalid_direction_id"),
        (lambda u: u.update(delay=10**6), "trip_delay_outside_24h"),
        (lambda u: u["trip"].update(start_date="2026-07-07"), "invalid_start_date"),
        (lambda u: u.update(timestamp="soon"), "invalid_update_timestamp"),
    ],
)
def test_bad_trip_fields_are_quarantined(mutation, reason):
    payload = feeds.trip_updates(NOW)
    mutation(payload["response"]["entity"][0]["trip_update"])
    parsed = parse_trip_updates(payload, NOW)
    assert reason in [r for r, _ in parsed.rejects]
    assert "T1" not in by_trip(parsed.rows)


def test_bad_stop_update_keeps_the_trip():
    payload = feeds.trip_updates(NOW)
    payload["response"]["entity"][0]["trip_update"]["stop_time_update"]["arrival"]["delay"] = "late"
    parsed = parse_trip_updates(payload, NOW)
    assert "invalid_arrival_delay" in [r for r, _ in parsed.rejects]
    assert by_trip(parsed.rows)["T1"]["stop_id"] is None  # trip-level row survives


def test_envelope_errors():
    with pytest.raises(FeedError):
        parse_trip_updates({"status": "ERROR", "response": {}}, NOW)
    with pytest.raises(FeedError):
        parse_trip_updates({"response": {"entity": {}}}, NOW)
    with pytest.raises(FeedError):
        parse_trip_updates(["not", "an", "object"], NOW)
    empty = parse_trip_updates({"response": {"header": {}, "entity": []}}, NOW)
    assert empty.entity_count == 0
    assert empty.feed_ts == NOW


def test_vehicle_positions():
    parsed = parse_vehicle_positions(feeds.vehicle_positions(NOW), NOW)
    rows = {row["vehicle_id"]: row for row in parsed.rows}
    assert set(rows) == {"V1", "V2", "V3", "V9", "V10"}
    assert [r for r, _ in parsed.rejects] == ["invalid_coordinates"]
    assert rows["V1"]["occupancy_status"] == "MANY_SEATS_AVAILABLE"
    assert rows["V2"]["occupancy_status"] == "STANDING_ROOM_ONLY"
    assert rows["V1"]["bearing"] == 90.0
    assert rows["V1"]["speed_kmh"] == 24
    assert rows["V9"]["trip_id"] is None
    assert rows["V9"]["service_date"].isoformat() == "2026-07-07"


def test_service_alerts():
    parsed = parse_service_alerts(feeds.service_alerts(NOW), NOW)
    alerts = {row["alert_id"]: row for row in parsed.rows}
    detour, future = alerts["alert-detour"], alerts["alert-future"]
    assert detour["header_text"].startswith("Detour")  # English translation preferred
    assert detour["active_at_last_seen"] is True
    assert future["active_at_last_seen"] is False
    assert future["effect"] == "NO_SERVICE"
    assert future["cause"] == "MAINTENANCE"
    assert detour["severity"] == "WARNING"
    assert future["severity"] is None
    assert len([c for c in parsed.children if c["alert_version_id"] == detour["alert_version_id"]]) == 2
    changed = feeds.service_alerts(NOW)
    changed["response"]["entity"][0]["alert"]["effect"] = "NO_SERVICE"
    again = {r["alert_id"]: r for r in parse_service_alerts(changed, NOW).rows}
    assert again["alert-detour"]["alert_version_id"] != detour["alert_version_id"]
    assert again["alert-future"]["alert_version_id"] == future["alert_version_id"]


def test_field_helpers():
    assert enum_name({3: "CANCELED"}, 3) == "CANCELED"
    assert enum_name({3: "CANCELED"}, "3") == "CANCELED"
    assert enum_name({3: "CANCELED"}, 42) == "UNKNOWN_42"
    assert enum_name({}, "detour") == "DETOUR"
    assert epoch("1792571100.814", "x") is not None
    assert epoch(None, "x") is None
    assert translated({"translation": [{"text": "  hi "}]}) == "hi"
    assert translated(None) is None
