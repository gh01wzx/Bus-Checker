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


def fetch_realtime_trips():
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


def extract_delay_records(entities):
    captured_at = datetime.now(timezone.utc)
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


def load_to_database(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        logger.warning("No rows to store, skipping DB write")
        return

    df = pd.DataFrame(rows)

    with duckdb.connect(DB_PATH) as con:
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

    logger.info(f"Stored {len(rows)} rows into {DB_PATH}")


def run_pipeline():
    entities = fetch_realtime_trips()
    rows = extract_delay_records(entities)
    load_to_database(rows)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    run_pipeline()
