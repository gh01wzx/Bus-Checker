import logging
import os
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import requests

from bus_checker.database import bootstrap, connect, read_frame
from bus_checker.ingestion import ingest_payload

GTFS_DOWNLOAD_URL = "https://gtfs.at.govt.nz/gtfs.zip"
logger = logging.getLogger(__name__)


def find_gtfs_file(base_dir: Path, filename: str) -> Path:
    matches = list(base_dir.rglob(filename))
    if not matches:
        raise FileNotFoundError(f"Required file '{filename}' not found in {base_dir}")
    return matches[0]


def download_and_extract_gtfs(extract_to: Path) -> None:
    temp_zip_path = None
    try:
        url = os.getenv("AT_GTFS_URL", GTFS_DOWNLOAD_URL)
        logger.info("Downloading GTFS reference data")
        with requests.get(url, stream=True, timeout=30) as response:
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False) as tmp_zip:
                temp_zip_path = Path(tmp_zip.name)
                for chunk in response.iter_content(chunk_size=8192):
                    tmp_zip.write(chunk)

        logger.info(f"Extracting to {extract_to}...")
        with zipfile.ZipFile(temp_zip_path, "r") as zf:
            zf.extractall(extract_to)

        logger.info("Download and extraction complete.")
    except Exception:
        logger.exception("Failed to download or extract GTFS data")
        raise
    finally:
        if temp_zip_path and temp_zip_path.exists():
            temp_zip_path.unlink(missing_ok=True)


def load_gtfs(*, if_stale: bool = False) -> None:
    with connect(write=True) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS bus_reference_refresh "
            "(source VARCHAR PRIMARY KEY, refreshed_at TIMESTAMP WITH TIME ZONE NOT NULL)"
        )
        if if_stale and conn.execute(
            "SELECT 1 FROM bus_reference_refresh WHERE source = 'gtfs' "
            "AND refreshed_at > CURRENT_TIMESTAMP - interval '7 days'"
        ).fetchone():
            return
    with tempfile.TemporaryDirectory() as tmpdir:
        gtfs_dir = Path(tmpdir)
        download_and_extract_gtfs(gtfs_dir)

        routes = pd.read_csv(
            find_gtfs_file(gtfs_dir, "routes.txt"),
            dtype={"route_id": str, "route_short_name": str},
        )[["route_id", "route_short_name", "route_type"]]
        trips = pd.read_csv(
            find_gtfs_file(gtfs_dir, "trips.txt"), dtype={"route_id": str}
        )[["route_id", "trip_headsign", "direction_id"]]
        stops = pd.read_csv(
            find_gtfs_file(gtfs_dir, "stops.txt"), dtype={"stop_id": str}
        )[["stop_id", "stop_name", "stop_lat", "stop_lon"]]

        tables = {"gtfs_routes": routes, "gtfs_trips": trips, "gtfs_stops": stops}
        for name, frame in tables.items():
            if frame.empty:
                raise ValueError(f"Empty GTFS reference: {name}")
        for identifiers in (routes["route_id"], stops["stop_id"]):
            if identifiers.isna().any() or identifiers.str.strip().eq("").any():
                raise ValueError(f"Missing GTFS identifier: {identifiers.name}")
            if not identifiers.is_unique:
                raise ValueError(f"Duplicate GTFS identifier: {identifiers.name}")

        with connect(write=True) as conn:
            for name, frame in tables.items():
                if conn.kind == "duckdb":
                    conn.connection.register("_gtfs_frame", frame)
                    conn.execute(
                        f"CREATE TABLE IF NOT EXISTS {name} AS SELECT * FROM _gtfs_frame LIMIT 0"
                    )
                    conn.execute(f"DELETE FROM {name}")
                    conn.execute(
                        f"INSERT INTO {name} BY NAME SELECT * FROM _gtfs_frame"
                    )
                    conn.connection.unregister("_gtfs_frame")
                else:
                    frame.head(0).to_sql(
                        name, conn.connection, if_exists="append", index=False
                    )
                    conn.execute(f"DELETE FROM {name}")
                    frame.to_sql(
                        name,
                        conn.connection,
                        if_exists="append",
                        index=False,
                        chunksize=5000,
                    )

            conn.execute("DELETE FROM bus_reference_refresh WHERE source = 'gtfs'")
            conn.execute(
                "INSERT INTO bus_reference_refresh VALUES ('gtfs', CURRENT_TIMESTAMP)"
            )
        logger.info("Loaded GTFS reference tables into the selected warehouse.")


def import_history():
    with connect(write=True) as conn:
        bootstrap(conn)
    frame = read_frame(
        """SELECT p.captured_at, p.route_id, p.trip_id, p.delay, p.direction_id
        FROM trip_punctuality p WHERE NOT EXISTS (
            SELECT 1 FROM bus_observations o WHERE o.observation_type='trip'
            AND o.captured_at=p.captured_at AND o.route_id=p.route_id
            AND o.trip_id=p.trip_id AND o.delay=p.delay
            AND o.direction_id IS NOT DISTINCT FROM p.direction_id)"""
    )
    if frame.empty:
        print("No trip history to import.")
        return
    frame["captured_at"] = pd.to_datetime(frame["captured_at"], utc=True)
    accepted, rejected = 0, 0
    for captured, group in frame.groupby("captured_at", sort=True):
        if not isinstance(captured, pd.Timestamp):
            raise ValueError("Invalid historical capture timestamp")
        entities = []
        for row in group.to_dict(orient="records"):
            entities.append(
                {
                    "trip_update": {
                        "trip": {
                            "route_id": (
                                None if pd.isna(row["route_id"]) else str(row["route_id"])
                            ),
                            "trip_id": (
                                None if pd.isna(row["trip_id"]) else str(row["trip_id"])
                            ),
                            "direction_id": (
                                None
                                if pd.isna(row["direction_id"])
                                else int(row["direction_id"])
                            ),
                        },
                        "delay": None if pd.isna(row["delay"]) else int(row["delay"]),
                    }
                }
            )
        payload = {
            "header": {
                "timestamp": int(captured.timestamp()),
                "historical_capture": captured.isoformat(),
            },
            "entity": entities,
        }
        result = ingest_payload(payload, write_legacy=False)
        accepted += result["accepted_rows"]
        rejected += result["rejected_rows"]
    print(
        f"History import complete: {accepted} new observations; {rejected} rejected. Legacy tables unchanged."
    )
