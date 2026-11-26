import logging
import os
import uuid
import time
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from bus_checker.parsing import canonical, digest, normalize, unpack_feed
from bus_checker.database import Connection, bootstrap, connect

TRIP_UPDATES_URL = "https://api.at.govt.nz/realtime/legacy/tripupdates"
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
            os.getenv("AT_TRIP_UPDATES_URL", TRIP_UPDATES_URL),
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


def insert_raw_batch(
    connection: Connection,
    payload: dict,
    batch_id: str,
    captured_at: datetime,
    loaded_at: datetime,
) -> bool:
    """Claim the batch in the same transaction as its observations and audit."""
    result = connection.execute(
        """
        INSERT INTO bus_raw_batches (batch_id, captured_at, loaded_at, payload)
        VALUES (:batch, :captured, :loaded, :payload)
        ON CONFLICT (batch_id) DO NOTHING
        RETURNING batch_id
    """,
        {
            "batch": batch_id,
            "captured": captured_at,
            "loaded": loaded_at,
            "payload": canonical(payload),
        },
    )
    return result.fetchone() is not None


def write_observations(
    connection: Connection,
    batch_id: str,
    captured_at: datetime,
    loaded_at: datetime,
    accepted: dict,
    write_legacy: bool,
) -> None:
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


def write_quarantine(connection: Connection, batch_id: str, rejected: list) -> None:
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
        inserted = insert_raw_batch(
            connection, payload, batch_id, captured_at, started_at
        )
        if inserted:
            write_observations(
                connection, batch_id, captured_at, started_at, accepted, write_legacy
            )
            write_quarantine(connection, batch_id, rejected)
            status = "warning" if rejected or not accepted else "success"
        else:
            status = "duplicate"

        result = {
            "run_id": run_id,
            "batch_id": batch_id,
            "status": status,
            "accepted_rows": len(accepted) if inserted else 0,
            "rejected_rows": len(rejected) if inserted else 0,
            "duplicate_rows": duplicates if inserted else duplicates + len(accepted),
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


def collect_burst(bursts=5, interval_seconds=300):
    failed = 0
    for index in range(bursts):
        logger.info("Burst %s/%s", index + 1, bursts)
        try:
            run_pipeline()
        except Exception:
            failed += 1
            logger.exception("Burst %s failed, continuing", index + 1)
        if index < bursts - 1:
            time.sleep(interval_seconds)
    if failed:
        raise SystemExit(f"{failed}/{bursts} collections failed; check ingestion audit")
