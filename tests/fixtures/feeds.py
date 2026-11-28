"""Deterministic AT-style realtime payloads, relative to a reference time.

Snapshot 1 (``now``):
  T1 bus 101 dir 0, +90 s observed  -> on time
  T2 bus 101 dir 1, +late s observed -> late
  T3 bus 70,        -120 s observed  -> early (departure only)
  T4 bus 70,        future arrival   -> prediction, excluded
  T5 bus 101,       cancelled, no stop updates
  T6 train WEST,    +30 s observed   -> on time
  one entity without trip_id        -> quarantined (missing_trip_id)
Snapshot 2 (``now + 5 min``, ``second=True``): T1 unchanged (de-duplicated), T2 reaches stop 3.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

AUCKLAND = ZoneInfo("Pacific/Auckland")


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


def service_date(now: datetime) -> str:
    return now.astimezone(AUCKLAND).strftime("%Y%m%d")


def _envelope(now: datetime, entities: list) -> dict:
    return {
        "status": "OK",
        "response": {
            "header": {"timestamp": now.timestamp(), "gtfs_realtime_version": "1.0", "incrementality": 0},
            "entity": entities,
        },
        "error": None,
    }


def _trip(trip_id: str, route_id: str, direction: int, start: str, now: datetime, relationship: int = 0) -> dict:
    return {
        "trip_id": trip_id,
        "route_id": route_id,
        "direction_id": direction,
        "start_date": service_date(now),
        "start_time": start,
        "schedule_relationship": relationship,
    }


def trip_updates(now: datetime, *, late_delay: int = 420, second: bool = False) -> dict:
    t = _epoch(now)
    first = now - timedelta(minutes=5) if second else now
    t0 = _epoch(first)
    t2_update = (
        {"stop_sequence": 3, "stop_id": "1001-aaaa1111", "arrival": {"delay": late_delay + 60, "time": t - 60}}
        if second
        else {"stop_sequence": 2, "stop_id": "1002-bbbb2222", "arrival": {"delay": late_delay, "time": t - 60}}
    )
    entities = [
        {
            "id": "T1",
            "is_deleted": False,
            "trip_update": {
                "trip": _trip("T1", "101-202", 0, "07:00:00", now),
                "stop_time_update": {
                    "stop_sequence": 2,
                    "stop_id": "1002-bbbb2222",
                    "arrival": {"delay": 90, "time": t0 - 120, "uncertainty": 0},
                    "schedule_relationship": 0,
                },
                "vehicle": {"id": "V1", "label": "NB   101"},
                "timestamp": t0 - 100,
                "delay": 90,
            },
        },
        {
            "id": "T2",
            "is_deleted": False,
            "trip_update": {
                "trip": _trip("T2", "101-202", 1, "08:00:00", now),
                "stop_time_update": [{**t2_update, "schedule_relationship": 0}],
                "vehicle": {"id": "V2", "label": "NB 102"},
                "timestamp": t - 50,
                "delay": t2_update["arrival"]["delay"],
            },
        },
        {
            "id": "T3",
            "is_deleted": False,
            "trip_update": {
                "trip": _trip("T3", "70-203", 0, "07:30:00", now),
                "stop_time_update": {
                    "stop_sequence": 1,
                    "stop_id": "2002-eeee5555",
                    "departure": {"delay": -120, "time": t0 - 300},
                    "schedule_relationship": 0,
                },
                "vehicle": {"id": "V3", "label": "RT 70"},
                "timestamp": t0 - 280,
                "delay": -120,
            },
        },
        {
            "id": "T4",
            "is_deleted": False,
            "trip_update": {
                "trip": _trip("T4", "70-203", 0, "09:30:00", now),
                "stop_time_update": {
                    "stop_sequence": 1,
                    "stop_id": "2002-eeee5555",
                    "arrival": {"delay": 30, "time": t + 600},
                    "schedule_relationship": 0,
                },
                "vehicle": {"id": "V4", "label": "RT 71"},
                "timestamp": t - 30,
                "delay": 30,
            },
        },
        {
            "id": "T5",
            "is_deleted": False,
            "trip_update": {
                "trip": _trip("T5", "101-202", 0, "10:00:00", now, relationship=3),
                "timestamp": t0 - 3600,
                "delay": 0,
            },
        },
        {
            "id": "T6",
            "is_deleted": False,
            "trip_update": {
                "trip": _trip("T6", "WEST-201", 0, "07:15:00", now),
                "stop_time_update": {
                    "stop_sequence": 1,
                    "stop_id": "9001-ffff6666",
                    "arrival": {"delay": 30, "time": t0 - 200},
                    "departure": {"delay": 40, "time": t0 - 160},
                    "schedule_relationship": 0,
                },
                "vehicle": {"id": "V6", "label": "AMP 6"},
                "timestamp": t0 - 150,
                "delay": 30,
            },
        },
        {"id": "bad", "trip_update": {"trip": {"route_id": "101-202"}, "delay": 5}},
    ]
    return _envelope(now, entities)


def vehicle_positions(now: datetime) -> dict:
    t = _epoch(now)

    def vehicle(vid: str, lat: float, lon: float, trip: dict | None, occupancy: int | None, speed: float) -> dict:
        body: dict = {
            "position": {"latitude": lat, "longitude": lon, "speed": speed, "bearing": "90"},
            "timestamp": t - 20,
            "vehicle": {"id": vid, "label": f"Bus {vid}", "license_plate": f"PL{vid}"},
        }
        if trip is not None:
            body["trip"] = trip
        if occupancy is not None:
            body["occupancy_status"] = occupancy
        return {"id": vid, "is_deleted": False, "vehicle": body}

    entities = [
        vehicle("V1", -36.8580, 174.7550, _trip("T1", "101-202", 0, "07:00:00", now), 1, 24),
        vehicle("V2", -36.8485, 174.7633, _trip("T2", "101-202", 1, "08:00:00", now), 3, 18),
        vehicle("V3", -36.9000, 174.8500, _trip("T3", "70-203", 0, "07:30:00", now), 0, 32),
        vehicle("V9", -36.8800, 174.7700, None, None, 0),
        vehicle("V10", -41.2865, 174.7762, None, None, 0),  # Wellington: outside the region
        {"id": "broken", "vehicle": {"position": {"latitude": 0, "longitude": 0}, "vehicle": {"id": "X"}}},
    ]
    return _envelope(now, entities)


def service_alerts(now: datetime) -> dict:
    t = _epoch(now)
    entities = [
        {
            "id": "alert-detour",
            "is_deleted": False,
            "alert": {
                "active_period": [{"start": t - 3600, "end": t + 3600}],
                "informed_entity": [
                    {"route_id": "101-202", "stop_id": "1002-bbbb2222"},
                    {"route_id": "101-202"},
                ],
                "cause": "CONSTRUCTION",
                "effect": "DETOUR",
                "severity_level": "WARNING",
                "header_text": {
                    "translation": [
                        {"text": "Kia ora", "language": "mi"},
                        {"text": "Detour: Route 101 - Karangahape Road", "language": "en"},
                    ]
                },
                "description_text": {"translation": [{"text": "Buses detour via Pitt Street.", "language": "en"}]},
            },
        },
        {
            "id": "alert-future",
            "is_deleted": False,
            "alert": {
                "active_period": [{"start": t + 86400, "end": t + 2 * 86400}],
                "informed_entity": [{"route_id": "70-203"}],
                "cause": 9,
                "effect": 1,
                "header_text": {"translation": [{"text": "No service: Route 70 tomorrow", "language": "en"}]},
            },
        },
    ]
    return _envelope(now, entities)
