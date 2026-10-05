import argparse
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config
from feed_parser import canonical, digest, normalize, unpack_feed
from warehouse import Connection, bootstrap, connect

logger = logging.getLogger(__name__)

INSERT_OBSERVATIONS = """
    INSERT INTO bus_observations (
        observation_id, batch_id, captured_at, loaded_at, route_id, trip_id,
        direction_id, stop_id, stop_sequence, delay, observation_type
    ) VALUES (
        :id, :batch, :captured, :loaded, :route_id, :trip_id,
        :direction_id, :stop_id, :stop_sequence, :delay, :observation_type
    )
"""
INSERT_RUN = """
    INSERT INTO bus_ingestion_runs (
        run_id, batch_id, started_at, finished_at, status,
        accepted_rows, rejected_rows, duplicate_rows, error_code
    ) VALUES (
        :run_id, :batch_id, :started, :finished, :status,
        :accepted_rows, :rejected_rows, :duplicate_rows, :error
    )
"""


def fetch_feed() -> dict:
    key = os.getenv("AT_SUB_KEY")
    if not key:
        raise ValueError("AT_SUB_KEY is required for live collection")
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True,
    )
    with requests.Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=retry))
        response = session.get(
            config.TRIP_UPDATES_URL,
            headers={"Ocp-Apim-Subscription-Key": key},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()


def write_compatibility_tables(
    connection: Connection, observations: list[dict]
) -> None:
    trip_columns = ["captured", "route_id", "trip_id", "delay", "direction_id"]
    stop_columns = [
        "captured",
        "route_id",
        "trip_id",
        "stop_id",
        "stop_sequence",
        "delay",
    ]
    trips, stops = [], []
    for observation in observations:
        if observation["observation_type"] == "trip":
            trips.append({column: observation[column] for column in trip_columns})
        else:
            stops.append({column: observation[column] for column in stop_columns})
    connection.many(
        """
        INSERT INTO trip_punctuality (captured_at, route_id, trip_id, delay, direction_id)
        VALUES (:captured, :route_id, :trip_id, :delay, :direction_id)
    """,
        trips,
    )
    connection.many(
        """
        INSERT INTO stop_punctuality (captured_at, route_id, trip_id, stop_id, stop_sequence, delay)
        VALUES (:captured, :route_id, :trip_id, :stop_id, :stop_sequence, :delay)
    """,
        stops,
    )


def write_batch(
    connection,
    payload,
    batch_id,
    captured_at,
    loaded_at,
    accepted,
    rejected,
    write_legacy,
):
    connection.execute(
        """
        INSERT INTO bus_raw_batches (batch_id, captured_at, loaded_at, payload)
        VALUES (:batch, :captured, :loaded, :payload)
    """,
        {
            "batch": batch_id,
            "captured": captured_at,
            "loaded": loaded_at,
            "payload": canonical(payload),
        },
    )

    observations = [
        {
            **row,
            "id": key,
            "batch": batch_id,
            "captured": captured_at,
            "loaded": loaded_at,
        }
        for key, row in accepted.items()
    ]
    connection.many(INSERT_OBSERVATIONS, observations)
    if write_legacy:
        write_compatibility_tables(connection, observations)

    quarantined = [
        {
            "id": digest([batch_id, index]),
            "batch": batch_id,
            "reason": reason,
            "payload": canonical(record),
        }
        for index, (reason, record) in enumerate(rejected)
    ]
    connection.many(
        """
        INSERT INTO bus_quarantine (rejection_id, batch_id, reason, payload)
        VALUES (:id, :batch, :reason, :payload)
    """,
        quarantined,
    )


def ingest_payload(
    payload: dict, run_id: str | None = None, write_legacy: bool = True
) -> dict:
    started_at = datetime.now(timezone.utc)
    run_id = run_id or str(uuid.uuid4())
    feed, captured_at = unpack_feed(payload)
    ordered_entities = sorted(feed["entity"], key=canonical)
    batch_id = digest({**feed, "entity": ordered_entities})
    accepted, rejected, duplicates = normalize(ordered_entities, batch_id)

    with connect(write=True) as connection:
        bootstrap(connection)
        existing = connection.execute(
            "SELECT batch_id FROM bus_raw_batches WHERE batch_id = :batch",
            {"batch": batch_id},
        ).fetchone()
        if existing:
            status = "duplicate"
        elif rejected or not accepted:
            status = "warning"
        else:
            status = "success"

        if not existing:
            write_batch(
                connection,
                payload,
                batch_id,
                captured_at,
                started_at,
                accepted,
                rejected,
                write_legacy,
            )

        result = {
            "run_id": run_id,
            "batch_id": batch_id,
            "status": status,
            "accepted_rows": 0 if existing else len(accepted),
            "rejected_rows": 0 if existing else len(rejected),
            "duplicate_rows": len(accepted) + duplicates if existing else duplicates,
        }
        connection.execute(
            INSERT_RUN,
            {
                **result,
                "started": started_at,
                "finished": datetime.now(timezone.utc),
                "error": None,
            },
        )
    logger.info(
        "Ingestion %s: accepted=%s rejected=%s duplicates=%s",
        status,
        result["accepted_rows"],
        result["rejected_rows"],
        result["duplicate_rows"],
    )
    return result


def record_failure(run_id: str, started_at: datetime, error: Exception) -> None:
    try:
        with connect(write=True) as connection:
            bootstrap(connection)
            connection.execute(
                INSERT_RUN,
                {
                    "run_id": run_id,
                    "batch_id": None,
                    "started": started_at,
                    "finished": datetime.now(timezone.utc),
                    "status": "failed",
                    "accepted_rows": 0,
                    "rejected_rows": 0,
                    "duplicate_rows": 0,
                    "error": type(error).__name__,
                },
            )
    except Exception:
        logger.error("Could not persist failed-run audit")


def run_pipeline(payload: dict | None = None) -> dict:
    started_at = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())
    try:
        feed = fetch_feed() if payload is None else payload
        return ingest_payload(feed, run_id)
    except Exception as error:
        record_failure(run_id, started_at, error)
        raise


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(
        description="Collect AT data or backfill an archived JSON feed"
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--file", type=Path, help="Ingest a saved feed; safe to rerun")
    source.add_argument(
        "--replay", help="Verify replay of an archived batch; exact replay is a no-op"
    )
    args = parser.parse_args()

    payload = None
    if args.file:
        payload = json.loads(args.file.read_text(encoding="utf-8"))
    elif args.replay:
        with connect() as connection:
            row = connection.execute(
                "SELECT payload FROM bus_raw_batches WHERE batch_id = :id",
                {"id": args.replay},
            ).fetchone()
        if row is None:
            parser.error("Unknown batch ID")
        payload = json.loads(row[0])
    print(json.dumps(run_pipeline(payload), indent=2))
