"""Pure parsers for AT's GTFS-Realtime JSON feeds.

Each parser turns a decoded payload into rows for one raw table plus a list of rejected
records with a machine-readable reason. Parsers never touch the database or the clock
(except as an explicit ``received_at`` fallback), which keeps them easy to test.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from bus_checker.config import LOCAL_TZ
from bus_checker.ids import canonical_json, sha256_hex, stable_uuid

AUCKLAND = ZoneInfo(LOCAL_TZ)
MAX_DELAY_SEC = 24 * 60 * 60
MIN_EPOCH = 946_684_800  # 2000-01-01
MAX_EPOCH = 4_102_444_800  # 2100-01-01
MAX_INT32 = 2**31 - 1
MAX_SPEED_KMH = 250.0
START_TIME = re.compile(r"^([0-4]?\d):([0-5]\d):([0-5]\d)$")
WHITESPACE = re.compile(r"\s+")

# GTFS-Realtime enumerations. AT sends some as integers and some as names.
TRIP_SCHEDULE_RELATIONSHIP = {
    0: "SCHEDULED",
    1: "ADDED",
    2: "UNSCHEDULED",
    3: "CANCELED",
    5: "REPLACEMENT",
    6: "DUPLICATED",
    7: "DELETED",
    8: "NEW",
}
STOP_SCHEDULE_RELATIONSHIP = {0: "SCHEDULED", 1: "SKIPPED", 2: "NO_DATA", 3: "UNSCHEDULED"}
OCCUPANCY_STATUS = {
    0: "EMPTY",
    1: "MANY_SEATS_AVAILABLE",
    2: "FEW_SEATS_AVAILABLE",
    3: "STANDING_ROOM_ONLY",
    4: "CRUSHED_STANDING_ROOM_ONLY",
    5: "FULL",
    6: "NOT_ACCEPTING_PASSENGERS",
    7: "NO_DATA_AVAILABLE",
    8: "NOT_BOARDABLE",
}
ALERT_CAUSE = {
    1: "UNKNOWN_CAUSE",
    2: "OTHER_CAUSE",
    3: "TECHNICAL_PROBLEM",
    4: "STRIKE",
    5: "DEMONSTRATION",
    6: "ACCIDENT",
    7: "HOLIDAY",
    8: "WEATHER",
    9: "MAINTENANCE",
    10: "CONSTRUCTION",
    11: "POLICE_ACTIVITY",
    12: "MEDICAL_EMERGENCY",
}
ALERT_EFFECT = {
    1: "NO_SERVICE",
    2: "REDUCED_SERVICE",
    3: "SIGNIFICANT_DELAYS",
    4: "DETOUR",
    5: "ADDITIONAL_SERVICE",
    6: "MODIFIED_SERVICE",
    7: "OTHER_EFFECT",
    8: "UNKNOWN_EFFECT",
    9: "STOP_MOVED",
    10: "NO_EFFECT",
    11: "ACCESSIBILITY_ISSUE",
}
ALERT_SEVERITY = {1: "UNKNOWN_SEVERITY", 2: "INFO", 3: "WARNING", 4: "SEVERE"}


class FeedError(ValueError):
    """The payload as a whole is unusable (wrong envelope, API error, bad header)."""


class Reject(ValueError):
    """A single record is unusable. ``str(error)`` is the quarantine reason."""


@dataclass
class ParsedFeed:
    feed: str
    feed_ts: datetime
    entity_count: int
    rows: list[dict[str, Any]] = field(default_factory=list)
    children: list[dict[str, Any]] = field(default_factory=list)
    rejects: list[tuple[str, Any]] = field(default_factory=list)
    duplicates: int = 0
    skipped: int = 0


# --------------------------------------------------------------------------------------
# Field coercion
# --------------------------------------------------------------------------------------
def epoch(value: Any, name: str) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise Reject(f"invalid_{name}")
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        raise Reject(f"invalid_{name}") from None
    if not MIN_EPOCH <= seconds <= MAX_EPOCH:
        raise Reject(f"invalid_{name}")
    return datetime.fromtimestamp(seconds, UTC)


def whole_number(value: Any, name: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise Reject(f"invalid_{name}")
    if isinstance(value, float):
        if not value.is_integer():
            raise Reject(f"invalid_{name}")
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            raise Reject(f"invalid_{name}") from None
    raise Reject(f"invalid_{name}")


def number(value: Any) -> float | None:
    """Lenient float for descriptive attributes (bearing, speed). Bad values become None."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def delay(value: Any, name: str) -> int | None:
    seconds = whole_number(value, name)
    if seconds is not None and abs(seconds) > MAX_DELAY_SEC:
        raise Reject(f"{name}_outside_24h")
    return seconds


def identifier(value: Any) -> str | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    return text or None


def label(value: Any) -> str | None:
    text = identifier(value)
    return WHITESPACE.sub(" ", text) if text else None


def enum_name(mapping: Mapping[int, str], value: Any, default: str | None = None) -> str | None:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return mapping.get(value, f"UNKNOWN_{value}")
    text = str(value).strip().upper()
    if text.isdigit():
        return mapping.get(int(text), f"UNKNOWN_{text}")
    return text or default


def gtfs_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if len(text) != 8 or not text.isdigit():
        raise Reject("invalid_start_date")
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        raise Reject("invalid_start_date") from None


def start_time(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    match = START_TIME.match(text)
    if not match or int(match.group(1)) > 47:
        raise Reject("invalid_start_time")
    hours, minutes, seconds = match.groups()
    return f"{int(hours):02d}:{minutes}:{seconds}"


def local_date(moment: datetime) -> date:
    return moment.astimezone(AUCKLAND).date()


def translated(value: Any) -> str | None:
    """Pick the English (or first) translation of a GTFS-RT TranslatedString."""
    if isinstance(value, str):
        return value.strip() or None
    if not isinstance(value, dict):
        return None
    translations = value.get("translation")
    if not isinstance(translations, list):
        return None
    texts = [t for t in translations if isinstance(t, dict) and isinstance(t.get("text"), str)]
    if not texts:
        return None
    english = [t for t in texts if str(t.get("language", "")).lower().startswith("en")]
    chosen = (english or texts)[0]["text"].strip()
    return chosen or None


# --------------------------------------------------------------------------------------
# Envelope
# --------------------------------------------------------------------------------------
def unpack(payload: Any, received_at: datetime) -> tuple[datetime, list[Any]]:
    """Validate the AT envelope and return (feed timestamp, entities)."""
    if not isinstance(payload, dict):
        raise FeedError("payload_not_object")
    if payload.get("error"):
        raise FeedError("api_error")
    status = payload.get("status")
    if status is not None and str(status).upper() != "OK":
        raise FeedError("api_status_not_ok")
    feed = payload.get("response", payload)
    if not isinstance(feed, dict):
        raise FeedError("missing_response")
    entities = feed.get("entity", [])
    if entities is None:
        entities = []
    if not isinstance(entities, list):
        raise FeedError("entity_not_list")
    header = feed.get("header") or {}
    if not isinstance(header, dict):
        raise FeedError("invalid_header")
    try:
        feed_ts = epoch(header.get("timestamp"), "header_timestamp")
    except Reject as error:
        raise FeedError(str(error)) from None
    return feed_ts or received_at, entities


def _trip_descriptor(trip: Any) -> dict[str, Any]:
    if not isinstance(trip, dict):
        raise Reject("missing_trip_descriptor")
    direction = whole_number(trip.get("direction_id"), "direction_id")
    if direction not in (None, 0, 1):
        raise Reject("invalid_direction_id")
    return {
        "trip_id": identifier(trip.get("trip_id")),
        "route_id": identifier(trip.get("route_id")),
        "direction_id": direction,
        "start_date": gtfs_date(trip.get("start_date")),
        "start_time": start_time(trip.get("start_time")),
        "trip_schedule_relationship": enum_name(
            TRIP_SCHEDULE_RELATIONSHIP, trip.get("schedule_relationship"), "SCHEDULED"
        ),
    }


def _stop_event(event: Any, name: str) -> tuple[int | None, datetime | None, int | None]:
    if event is None:
        return None, None, None
    if not isinstance(event, dict):
        raise Reject(f"invalid_{name}")
    return (
        delay(event.get("delay"), f"{name}_delay"),
        epoch(event.get("time"), f"{name}_time"),
        whole_number(event.get("uncertainty"), f"{name}_uncertainty"),
    )


# --------------------------------------------------------------------------------------
# Trip updates
# --------------------------------------------------------------------------------------
def parse_trip_updates(payload: Any, received_at: datetime) -> ParsedFeed:
    feed_ts, entities = unpack(payload, received_at)
    result = ParsedFeed("trip_updates", feed_ts, len(entities))
    seen: dict[str, dict[str, Any]] = {}

    for entity in entities:
        if not isinstance(entity, dict):
            result.rejects.append(("invalid_entity", entity))
            continue
        update = entity.get("trip_update")
        if update is None or entity.get("is_deleted") is True:
            result.skipped += 1
            continue
        try:
            if not isinstance(update, dict):
                raise Reject("invalid_trip_update")
            trip = _trip_descriptor(update.get("trip"))
            if trip["trip_id"] is None:
                raise Reject("missing_trip_id")
            vehicle = update.get("vehicle") if isinstance(update.get("vehicle"), dict) else {}
            update_ts = epoch(update.get("timestamp"), "update_timestamp")
            trip_delay = delay(update.get("delay"), "trip_delay")
        except Reject as error:
            result.rejects.append((str(error), entity))
            continue

        service_date = trip["start_date"] or local_date(update_ts or feed_ts)
        base = {
            "feed_ts": feed_ts,
            "service_date": service_date,
            "entity_id": identifier(entity.get("id")),
            "trip_id": trip["trip_id"],
            "route_id": trip["route_id"],
            "direction_id": trip["direction_id"],
            "start_time": trip["start_time"],
            "trip_schedule_relationship": trip["trip_schedule_relationship"],
            "vehicle_id": identifier(vehicle.get("id")),
            "vehicle_label": label(vehicle.get("label")),
            "update_ts": update_ts,
            "trip_delay_sec": trip_delay,
        }

        raw_stops = update.get("stop_time_update")
        if raw_stops is None:
            stops: list[Any] = []
        elif isinstance(raw_stops, dict):
            stops = [raw_stops]
        elif isinstance(raw_stops, list):
            stops = raw_stops
        else:
            result.rejects.append(("invalid_stop_time_update", raw_stops))
            stops = []

        rows: list[dict[str, Any]] = []
        for stop in stops:
            try:
                if not isinstance(stop, dict):
                    raise Reject("invalid_stop_time_update")
                stop_id = identifier(stop.get("stop_id"))
                sequence = whole_number(stop.get("stop_sequence"), "stop_sequence")
                if sequence is not None and not 0 <= sequence <= MAX_INT32:
                    raise Reject("invalid_stop_sequence")
                if stop_id is None and sequence is None:
                    raise Reject("missing_stop_reference")
                arrival_delay, arrival_ts, uncertainty = _stop_event(stop.get("arrival"), "arrival")
                departure_delay, departure_ts, _ = _stop_event(stop.get("departure"), "departure")
            except Reject as error:
                result.rejects.append((str(error), stop))
                continue
            rows.append(
                {
                    **base,
                    "stop_id": stop_id,
                    "stop_sequence": sequence,
                    "stop_schedule_relationship": enum_name(
                        STOP_SCHEDULE_RELATIONSHIP, stop.get("schedule_relationship"), "SCHEDULED"
                    ),
                    "arrival_delay_sec": arrival_delay,
                    "arrival_ts": arrival_ts,
                    "arrival_uncertainty_sec": uncertainty,
                    "departure_delay_sec": departure_delay,
                    "departure_ts": departure_ts,
                }
            )
        if not rows:
            rows.append(
                {
                    **base,
                    "stop_id": None,
                    "stop_sequence": None,
                    "stop_schedule_relationship": None,
                    "arrival_delay_sec": None,
                    "arrival_ts": None,
                    "arrival_uncertainty_sec": None,
                    "departure_delay_sec": None,
                    "departure_ts": None,
                }
            )

        for row in rows:
            key = stable_uuid(
                "trip_update",
                row["trip_id"],
                row["service_date"],
                row["stop_id"],
                row["stop_sequence"],
                row["update_ts"] or row["feed_ts"],
                row["trip_delay_sec"],
                row["arrival_delay_sec"],
                row["arrival_ts"],
                row["departure_delay_sec"],
                row["departure_ts"],
                row["trip_schedule_relationship"],
            )
            _keep(result, seen, key, {"update_id": key, **row}, "update_id")
    result.rows = list(seen.values())
    return result


# --------------------------------------------------------------------------------------
# Vehicle positions
# --------------------------------------------------------------------------------------
def parse_vehicle_positions(payload: Any, received_at: datetime) -> ParsedFeed:
    feed_ts, entities = unpack(payload, received_at)
    result = ParsedFeed("vehicle_positions", feed_ts, len(entities))
    seen: dict[str, dict[str, Any]] = {}

    for entity in entities:
        if not isinstance(entity, dict):
            result.rejects.append(("invalid_entity", entity))
            continue
        vehicle = entity.get("vehicle")
        if vehicle is None or entity.get("is_deleted") is True:
            result.skipped += 1
            continue
        try:
            if not isinstance(vehicle, dict):
                raise Reject("invalid_vehicle")
            position = vehicle.get("position")
            if not isinstance(position, dict):
                raise Reject("missing_position")
            latitude, longitude = number(position.get("latitude")), number(position.get("longitude"))
            if latitude is None or longitude is None:
                raise Reject("missing_coordinates")
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180) or (latitude == 0 and longitude == 0):
                raise Reject("invalid_coordinates")
            descriptor = vehicle.get("vehicle") if isinstance(vehicle.get("vehicle"), dict) else {}
            vehicle_id = identifier(descriptor.get("id")) or identifier(entity.get("id"))
            if vehicle_id is None:
                raise Reject("missing_vehicle_id")
            trip = (
                _trip_descriptor(vehicle["trip"])
                if isinstance(vehicle.get("trip"), dict)
                else dict.fromkeys(
                    (
                        "trip_id",
                        "route_id",
                        "direction_id",
                        "start_date",
                        "start_time",
                        "trip_schedule_relationship",
                    )
                )
            )
            position_ts = epoch(vehicle.get("timestamp"), "position_timestamp") or feed_ts
        except Reject as error:
            result.rejects.append((str(error), entity))
            continue

        bearing = number(position.get("bearing"))
        speed = number(position.get("speed"))  # AT reports km/h despite the GTFS-RT spec
        odometer = number(position.get("odometer"))
        row = {
            "feed_ts": feed_ts,
            "position_ts": position_ts,
            "service_date": trip["start_date"] or local_date(position_ts),
            "entity_id": identifier(entity.get("id")),
            "vehicle_id": vehicle_id,
            "vehicle_label": label(descriptor.get("label")),
            "license_plate": label(descriptor.get("license_plate")),
            "trip_id": trip["trip_id"],
            "route_id": trip["route_id"],
            "direction_id": trip["direction_id"],
            "start_time": trip["start_time"],
            "trip_schedule_relationship": trip["trip_schedule_relationship"],
            "latitude": latitude,
            "longitude": longitude,
            "bearing": bearing if bearing is not None and 0 <= bearing <= 360 else None,
            "speed_kmh": speed if speed is not None and 0 <= speed <= MAX_SPEED_KMH else None,
            "odometer_m": odometer if odometer is not None and odometer >= 0 else None,
            "occupancy_status": enum_name(OCCUPANCY_STATUS, vehicle.get("occupancy_status")),
        }
        key = stable_uuid("vehicle_position", vehicle_id, position_ts, latitude, longitude)
        _keep(result, seen, key, {"position_id": key, **row}, "position_id")
    result.rows = list(seen.values())
    return result


# --------------------------------------------------------------------------------------
# Service alerts
# --------------------------------------------------------------------------------------
def _periods(raw: Any) -> list[tuple[datetime | None, datetime | None]]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise Reject("invalid_active_period")
    periods = []
    for period in raw:
        if not isinstance(period, dict):
            raise Reject("invalid_active_period")
        start = epoch(period.get("start"), "period_start")
        end = epoch(period.get("end"), "period_end")
        if start and end and end < start:
            raise Reject("inverted_active_period")
        periods.append((start, end))
    return periods


def parse_service_alerts(payload: Any, received_at: datetime) -> ParsedFeed:
    feed_ts, entities = unpack(payload, received_at)
    result = ParsedFeed("service_alerts", feed_ts, len(entities))
    seen: dict[str, dict[str, Any]] = {}
    children: dict[str, list[dict[str, Any]]] = {}

    for entity in entities:
        if not isinstance(entity, dict):
            result.rejects.append(("invalid_entity", entity))
            continue
        alert = entity.get("alert")
        if alert is None or entity.get("is_deleted") is True:
            result.skipped += 1
            continue
        try:
            if not isinstance(alert, dict):
                raise Reject("invalid_alert")
            alert_id = identifier(entity.get("id"))
            if alert_id is None:
                raise Reject("missing_alert_id")
            periods = _periods(alert.get("active_period"))
            informed = alert.get("informed_entity") or []
            if isinstance(informed, dict):
                informed = [informed]
            if not isinstance(informed, list):
                raise Reject("invalid_informed_entity")
        except Reject as error:
            result.rejects.append((str(error), entity))
            continue

        version = stable_uuid("service_alert", alert_id, sha256_hex(canonical_json(alert)))
        entities_rows = []
        for index, item in enumerate(informed):
            if not isinstance(item, dict):
                continue
            trip = item.get("trip") if isinstance(item.get("trip"), dict) else {}
            try:
                direction = whole_number(item.get("direction_id"), "direction_id")
            except Reject:
                direction = None
            entities_rows.append(
                {
                    "alert_version_id": version,
                    "entity_index": index,
                    "route_id": identifier(item.get("route_id")) or identifier(trip.get("route_id")),
                    "stop_id": identifier(item.get("stop_id")),
                    "trip_id": identifier(trip.get("trip_id")),
                    "direction_id": direction if direction in (0, 1) else None,
                }
            )
        starts = [start for start, _ in periods]
        ends = [end for _, end in periods]
        active_now = not periods or any(
            (start is None or start <= feed_ts) and (end is None or feed_ts <= end) for start, end in periods
        )
        row = {
            "alert_version_id": version,
            "alert_id": alert_id,
            "cause": enum_name(ALERT_CAUSE, alert.get("cause"), "UNKNOWN_CAUSE"),
            "effect": enum_name(ALERT_EFFECT, alert.get("effect"), "UNKNOWN_EFFECT"),
            "severity": enum_name(ALERT_SEVERITY, alert.get("severity_level")),
            "header_text": translated(alert.get("header_text")),
            "description_text": translated(alert.get("description_text")),
            "effect_detail": translated(alert.get("effect_detail")),
            "url": translated(alert.get("url")),
            "active_periods": canonical_json(
                [[s.isoformat() if s else None, e.isoformat() if e else None] for s, e in periods]
            ),
            "period_start": None if not starts or None in starts else min(s for s in starts if s),
            "period_end": None if not ends or None in ends else max(e for e in ends if e),
            "informed_entity_count": len(entities_rows),
            "active_at_last_seen": active_now,
        }
        if _keep(result, seen, version, row, "alert_version_id"):
            children[version] = entities_rows
    result.rows = list(seen.values())
    result.children = [child for rows in children.values() for child in rows]
    return result


def _keep(result: ParsedFeed, seen: dict[str, dict[str, Any]], key: str, row: dict[str, Any], _: str) -> bool:
    """De-duplicate within one payload. Returns True when the row is new."""
    existing = seen.get(key)
    if existing is None:
        seen[key] = row
        return True
    result.duplicates += 1
    return False


PARSERS: dict[str, Callable[[Any, datetime], ParsedFeed]] = {
    "trip_updates": parse_trip_updates,
    "vehicle_positions": parse_vehicle_positions,
    "service_alerts": parse_service_alerts,
}
