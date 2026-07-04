import os
import duckdb
import config
import requests
import tempfile
import logging
import zipfile

from pathlib import Path

DB_PATH = os.getenv("DUCKDB_PATH", "bus_data.duckdb")
GTFS_DOWNLOAD_URL = config.GTFS_DOWNLOAD_URL
logger = logging.getLogger(__name__)


def find_gtfs_file(base_dir: Path, filename: str) -> Path:
    matches = list(base_dir.rglob(filename))
    if not matches:
        raise FileNotFoundError(f"Required file '{filename}' not found in {base_dir}")
    return matches[0]


def download_and_extract_gtfs(extract_to: Path) -> None:
    temp_zip_path = None
    try:
        logger.info(f"Downloading GTFS from {GTFS_DOWNLOAD_URL}")
        resp = requests.get(GTFS_DOWNLOAD_URL, stream=True, timeout=30)
        resp.raise_for_status()

        with tempfile.NamedTemporaryFile(delete=False) as tmp_zip:
            for chunk in resp.iter_content(chunk_size=8192):
                tmp_zip.write(chunk)
            temp_zip_path = Path(tmp_zip.name)

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


def load_gtfs() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        gtfs_dir = Path(tmpdir)
        download_and_extract_gtfs(gtfs_dir)

        routes_file = find_gtfs_file(gtfs_dir, "routes.txt")
        trips_file = find_gtfs_file(gtfs_dir, "trips.txt")

        with duckdb.connect(DB_PATH) as con:
            con.execute(f"""
                CREATE OR REPLACE TABLE gtfs_routes AS
                SELECT route_id, route_short_name, route_type
                FROM read_csv_auto('{routes_file}')
            """)
            con.execute(f"""
                CREATE OR REPLACE TABLE gtfs_trips AS
                SELECT route_id, trip_headsign, direction_id
                FROM read_csv_auto('{trips_file}')
            """)

        logger.info("Loaded gtfs_routes and gtfs_trips into DuckDB.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    load_gtfs()
