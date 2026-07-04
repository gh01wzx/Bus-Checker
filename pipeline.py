import requests
import os
import config
import datetime
import duckdb
import pandas as pd
import logging

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TRIP_UPDATES_URL = config.TRIP_UPDATES_URL
SUB_KEY = os.environ["AT_SUB_KEY"]
DB_PATH = os.environ.get("DUCKDB_PATH", "bus_data.duckdb")
# 1 min early 5 mins late are consider on time
ON_TIME_EARLY = -60
ON_TIME_LATE = 5 * 60


def fetch_trip_updates():
    raw_resp = requests.get(
        TRIP_UPDATES_URL, headers={"Ocp-Apim-Subscription-Key": SUB_KEY}
    )

    if raw_resp.status_code != 200:
        print(f"Request failed with status {raw_resp.status_code}")
        print(raw_resp.text[:300])
        raise SystemExit(1)

    return raw_resp.json()["response"]["entity"]


def clean_rows(entities):
    captured_at = datetime.datetime.now()
    rows = []

    for trip in entities:
        tu = trip["trip_update"]
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

    return rows


def store_rows(rows):
    trip_punctuality_df = pd.DataFrame(rows)

    with duckdb.connect(DB_PATH) as db_con:
        db_con.execute("""
            CREATE TABLE IF NOT EXISTS trip_punctuality (
                captured_at  TIMESTAMP,
                route_id     VARCHAR,
                trip_id      VARCHAR,
                delay        INTEGER
            )
        """)
        db_con.execute("""
            INSERT INTO trip_punctuality (captured_at, route_id, trip_id, delay)
            SELECT captured_at, route_id, trip_id, delay FROM trip_punctuality_df
        """)

    logger.info("Stored %d rows into %s", len(rows), DB_PATH)


def run_once():
    entities = fetch_trip_updates()
    rows = clean_rows(entities)
    store_rows(rows)


if __name__ == "__main__":
    run_once()
