import hashlib
import json
from datetime import datetime, timezone
from typing import Any

MAX_DELAY_SECONDS = 24 * 60 * 60


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def unpack_feed(payload: dict) -> tuple[dict, datetime]:
    if not isinstance(payload, dict):
        raise ValueError("Feed must be a JSON object")
    feed = payload.get("response", payload)
    if not isinstance(feed, dict) or not isinstance(feed.get("entity"), list):
        raise ValueError("Feed must contain an entity array")
    header = feed.get("header") or {}
    if not isinstance(header, dict):
        raise ValueError("Invalid feed header")

    timestamp = header.get("timestamp")
    if timestamp is None:
        captured_at = datetime.now(timezone.utc)
    else:
        captured_at = datetime.fromtimestamp(int(timestamp), timezone.utc)
    return feed, captured_at


def integer(value: Any, name: str, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"invalid_{name}")
    try:
        return int(value)
    except (ValueError, TypeError):
        raise ValueError(f"invalid_{name}") from None


def identifier(value: Any, name: str) -> str:
    if (
        isinstance(value, bool)
        or not isinstance(value, (str, int))
        or not str(value).strip()
    ):
        raise ValueError(f"missing_{name}")
    return str(value)


def trip_fields(trip: dict) -> dict:
    fields = {
        "route_id": identifier(trip.get("route_id"), "route_id"),
        "trip_id": identifier(trip.get("trip_id"), "trip_id"),
        "direction_id": integer(
            trip.get("direction_id"), "direction_id", optional=True
        ),
    }
    if fields["direction_id"] not in (None, 0, 1):
        raise ValueError("invalid_direction_id")
    return fields


def stop_candidates(stops: list | dict, fields: dict) -> tuple[list, list]:
    if isinstance(stops, dict):
        stops = [stops]
    if not isinstance(stops, list):
        raise ValueError("invalid_stop_updates")

    candidates, rejected = [], []
    for stop in stops:
        if not isinstance(stop, dict):
            rejected.append(("invalid_stop_update", stop))
            continue
        arrival = stop.get("arrival") or {}
        departure = stop.get("departure") or {}
        if not isinstance(arrival, dict) or not isinstance(departure, dict):
            rejected.append(("invalid_stop_event", stop))
            continue
        delay = arrival.get("delay")
        if delay is None:
            delay = departure.get("delay")
        if delay is not None:
            candidates.append(
                {
                    **fields,
                    "delay": delay,
                    "stop_id": stop.get("stop_id"),
                    "stop_sequence": stop.get("stop_sequence"),
                    "observation_type": "stop",
                }
            )
    return candidates, rejected


def entity_candidates(entity: dict) -> tuple[list, list]:
    if not isinstance(entity, dict):
        raise ValueError("invalid_entity")
    update = entity.get("trip_update")
    if update is None:
        return [], []
    if not isinstance(update, dict) or not isinstance(update.get("trip"), dict):
        raise ValueError("missing_trip_descriptor")

    fields = trip_fields(update["trip"])
    candidates = []
    if update.get("delay") is not None:
        candidates.append(
            {
                **fields,
                "delay": update["delay"],
                "stop_id": None,
                "stop_sequence": None,
                "observation_type": "trip",
            }
        )
    stops, rejected = stop_candidates(update.get("stop_time_update") or [], fields)
    return candidates + stops, rejected


def validate_observation(candidate: dict) -> dict:
    candidate["delay"] = integer(candidate["delay"], "delay")
    if abs(candidate["delay"]) > MAX_DELAY_SECONDS:
        raise ValueError("delay_outside_24h_contract")
    if candidate["observation_type"] == "stop":
        candidate["stop_id"] = identifier(candidate["stop_id"], "stop_id")
        candidate["stop_sequence"] = integer(
            candidate["stop_sequence"], "stop_sequence", optional=True
        )
        if candidate["stop_sequence"] is not None and candidate["stop_sequence"] < 0:
            raise ValueError("invalid_stop_sequence")
    return candidate


def observation_id(batch_id: str, observation: dict) -> str:
    return digest(
        [
            batch_id,
            observation["route_id"],
            observation["trip_id"],
            observation["observation_type"],
            observation["stop_id"],
            observation["stop_sequence"],
        ]
    )


def normalize(entities: list, batch_id: str) -> tuple[dict, list, int]:
    accepted, rejected, duplicates = {}, [], 0
    for entity in entities:
        try:
            candidates, invalid_stops = entity_candidates(entity)
        except ValueError as error:
            rejected.append((str(error), entity))
            continue
        rejected.extend(invalid_stops)

        for candidate in candidates:
            try:
                observation = validate_observation(candidate)
            except ValueError as error:
                rejected.append((str(error), candidate))
                continue
            key = observation_id(batch_id, observation)
            if key not in accepted:
                accepted[key] = observation
            elif accepted[key] == observation:
                duplicates += 1
            else:
                rejected.append(("conflicting_duplicate_first_retained", observation))
    return accepted, rejected, duplicates
