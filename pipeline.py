import requests
import os
import config
import duckdb
import pandas as pd
import logging

from dotenv import load_dotenv
from typing import List, Dict, Any
from datetime import datetime, timezone

load_dotenv()

logger = logging.getLogger(__name__)

TRIP_UPDATES_URL = config.TRIP_UPDATES_URL
SUB_KEY = os.environ["AT_SUB_KEY"]
DB_PATH = os.environ.get("DUCKDB_PATH", "bus_data.duckdb")


def fetch_realtime_trips() -> List[Dict[str, Any]]:
    logger.info(f"Fetching trip updates from {TRIP_UPDATES_URL}")
    raw_resp = requests.get(
        TRIP_UPDATES_URL, headers={"Ocp-Apim-Subscription-Key": SUB_KEY}, timeout=30
    )

    if raw_resp.status_code != 200:
        logger.error(
            f"Request failed with status {raw_resp.status_code}: {raw_resp.text[:300]}"
        )
        raw_resp.raise_for_status()

    data: Dict[str, Any] = raw_resp.json()
    entities = data.get("response", {}).get("entity")

    if entities is None:
        raise ValueError("Unexpected API response structure: 'response.entity' missing")

    return entities


def extract_stop_records(
    entities: List[Dict[str, Any]], captured_at: datetime
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    for trip in entities:
        tu = trip.get("trip_update")
        if tu is None:
            continue

        stu = tu.get("stop_time_update")
        if stu is None:
            continue
        if isinstance(stu, dict):
            stu = [stu]

        route_id = tu["trip"]["route_id"]
        trip_id = tu["trip"]["trip_id"]

        for stop in stu:
            arrival = stop.get("arrival")
            departure = stop.get("departure")
            if arrival and arrival.get("delay") is not None:
                delay = arrival["delay"]
            elif departure and departure.get("delay") is not None:
                delay = departure["delay"]
            else:
                continue

            rows.append(
                {
                    "captured_at": captured_at,
                    "route_id": route_id,
                    "trip_id": trip_id,
                    "stop_id": stop.get("stop_id"),
                    "stop_sequence": stop.get("stop_sequence"),
                    "delay": delay,
                }
            )

    logger.info(f"Extracted {len(rows)} stop-level rows from {len(entities)} entities")

    return rows


def extract_delay_records(
    entities: List[Dict[str, Any]], captured_at: datetime
) -> List[Dict[str, Any]]:

    rows: List[Dict[str, Any]] = []

    for trip in entities:
        tu = trip.get("trip_update")
        if tu is None:
            continue

        delay = tu.get("delay")
        if delay is None:
            continue

        rows.append(
            {
                "captured_at": captured_at,
                "route_id": tu["trip"]["route_id"],
                "trip_id": tu["trip"]["trip_id"],
                "delay": delay,
            }
        )

    logger.info(f"Cleaned {len(rows)} valid rows from {len(entities)} entities")

    return rows


def load_to_database(rows: List[Dict[str, Any]], action_type: str) -> None:
    if not rows:
        logger.warning("No rows to store, skipping DB write")
        return

    df = pd.DataFrame(rows)

    with duckdb.connect(DB_PATH) as con:
        if action_type == "trip":
            con.execute("""
            CREATE TABLE IF NOT EXISTS trip_punctuality (
                captured_at  TIMESTAMP,
                route_id     VARCHAR,
                trip_id      VARCHAR,
                delay        INTEGER
            )
            """)
            con.register("temp_trip_updates", df)
            con.execute("""
            INSERT INTO trip_punctuality
            SELECT captured_at, route_id, trip_id, delay
            FROM temp_trip_updates
            """)
        elif action_type == "stop":
            con.execute("""
            CREATE TABLE IF NOT EXISTS stop_punctuality (
                captured_at     TIMESTAMP,
                route_id        VARCHAR,
                trip_id         VARCHAR,
                stop_id         VARCHAR,
                stop_sequence   INTEGER,
                delay           INTEGER        
                        )
            """)
            con.register("temp_stop_updates", df)
            con.execute("""
            INSERT INTO stop_punctuality
            SELECT captured_at, route_id, trip_id, stop_id, stop_sequence, delay
            FROM temp_stop_updates
            """)
        else:
            raise ValueError(f"Unknown action_type: {action_type}")

    logger.info(f"Stored {len(rows)} rows into {DB_PATH}")


def run_pipeline():
    entities = fetch_realtime_trips()
    captured_at = datetime.now(timezone.utc)

    trip_rows = extract_delay_records(entities, captured_at)
    load_to_database(trip_rows, "trip")

    stop_rows = extract_stop_records(entities, captured_at)
    load_to_database(stop_rows, "stop")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    run_pipeline()
