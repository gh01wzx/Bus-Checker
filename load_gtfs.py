import os
import config
import requests
import tempfile
import logging
import zipfile

from pathlib import Path
from sqlalchemy import create_engine

from dotenv import load_dotenv

load_dotenv()

DB_URL = os.environ["SUPABASE_DB_URL"]
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
    import pandas as pd

    with tempfile.TemporaryDirectory() as tmpdir:
        gtfs_dir = Path(tmpdir)
        download_and_extract_gtfs(gtfs_dir)

        routes = pd.read_csv(find_gtfs_file(gtfs_dir, "routes.txt"))[
            ["route_id", "route_short_name", "route_type"]
        ]
        trips = pd.read_csv(find_gtfs_file(gtfs_dir, "trips.txt"))[
            ["route_id", "trip_headsign", "direction_id"]
        ]
        stops = pd.read_csv(find_gtfs_file(gtfs_dir, "stops.txt"))[
            ["stop_id", "stop_name", "stop_lat", "stop_lon"]
        ]

        engine = create_engine(DB_URL)
        routes.to_sql("gtfs_routes", engine, if_exists="replace", index=False)
        trips.to_sql("gtfs_trips", engine, if_exists="replace", index=False)
        stops.to_sql("gtfs_stops", engine, if_exists="replace", index=False)
        engine.dispose()

        logger.info("Loaded gtfs_routes, gtfs_trips, gtfs_stops into Supabase.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    load_gtfs()
