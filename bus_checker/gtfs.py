"""GTFS static reference data: download, validate, derive and replace atomically.

Besides the core tables, the loader derives three compact tables so the warehouse never
needs the 1M-row ``stop_times.txt`` or 600k-row ``shapes.txt``:

* per-trip schedule summary (first departure, last arrival, stop count) on ``gtfs_trips``
* ``gtfs_route_stops``: the dominant stop pattern of every route direction
* ``gtfs_route_shapes``: a simplified line for every route direction (<= 200 points)
"""

from __future__ import annotations

import io
import json
import logging
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import IO, Any

import numpy as np
import pandas as pd
import requests

from bus_checker import __version__
from bus_checker.config import Settings
from bus_checker.ids import new_uuid
from bus_checker.schema import (
    GTFS_AGENCY,
    GTFS_CALENDAR,
    GTFS_CALENDAR_DATES,
    GTFS_LOADS,
    GTFS_ROUTE_SHAPES,
    GTFS_ROUTE_STOPS,
    GTFS_ROUTES,
    GTFS_STOPS,
    GTFS_TRIPS,
    Table,
    ensure_ready,
)
from bus_checker.warehouse import Warehouse, quote_identifier, session

logger = logging.getLogger(__name__)
MAX_SHAPE_POINTS = 200
MAX_ORPHAN_SHARE = 0.01
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class GtfsValidationError(ValueError):
    pass


@dataclass
class GtfsOutcome:
    status: str
    load_id: str | None = None
    sha256: str | None = None
    feed_version: str | None = None
    row_counts: dict[str, int] = field(default_factory=dict)
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------------------
# Source access
# --------------------------------------------------------------------------------------
class FeedFiles:
    """Read GTFS members by basename from a zip archive or a directory."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.zip: zipfile.ZipFile | None = None
        self.members: dict[str, str] = {}
        if path.is_dir():
            self.members = {p.name: str(p) for p in path.rglob("*.txt")}
        else:
            self.zip = zipfile.ZipFile(path)
            for info in self.zip.infolist():
                name = Path(info.filename).name
                if name.endswith(".txt") and name not in self.members:
                    self.members[name] = info.filename

    def __contains__(self, name: str) -> bool:
        return name in self.members

    @contextmanager
    def open(self, name: str) -> Iterator[IO[bytes]]:
        if name not in self.members:
            raise GtfsValidationError(f"Missing required GTFS file {name}")
        if self.zip is not None:
            with self.zip.open(self.members[name]) as handle:
                yield handle
        else:
            with open(self.members[name], "rb") as handle:
                yield handle

    def read(self, name: str, columns: list[str], required: tuple[str, ...] = ()) -> pd.DataFrame:
        with self.open(name) as handle:
            frame = pd.read_csv(
                handle,
                dtype=str,
                keep_default_na=False,
                encoding="utf-8-sig",
                usecols=lambda column: column.strip() in columns,
            )
        frame.columns = [c.strip() for c in frame.columns]
        missing = [c for c in required if c not in frame.columns]
        if missing:
            raise GtfsValidationError(f"{name} is missing column(s): {', '.join(missing)}")
        for column in columns:
            if column not in frame.columns:
                frame[column] = ""
            frame[column] = frame[column].str.strip()
        return frame[columns]

    def close(self) -> None:
        if self.zip is not None:
            self.zip.close()


# --------------------------------------------------------------------------------------
# Conversions
# --------------------------------------------------------------------------------------
def _null(series: pd.Series) -> pd.Series:
    return series.where(series != "", None)


def _int(series: pd.Series, name: str, allowed: set[int] | None = None) -> pd.Series:
    numeric = pd.to_numeric(series.where(series != ""), errors="coerce")
    bad = series.ne("") & numeric.isna()
    if bad.any():
        raise GtfsValidationError(f"{name} contains non-integer values")
    if allowed is not None and not numeric.dropna().isin(list(allowed)).all():
        raise GtfsValidationError(f"{name} contains values outside {sorted(allowed)}")
    return numeric.astype("Int64")


def _float(series: pd.Series, name: str, low: float, high: float) -> pd.Series:
    numeric = pd.to_numeric(series.where(series != ""), errors="coerce")
    if (series.ne("") & numeric.isna()).any():
        raise GtfsValidationError(f"{name} contains non-numeric values")
    if not numeric.dropna().between(low, high).all():
        raise GtfsValidationError(f"{name} is outside [{low}, {high}]")
    return numeric


def _dates(series: pd.Series, name: str) -> pd.Series:
    parsed = pd.to_datetime(series, format="%Y%m%d", errors="coerce")
    if parsed.isna().any():
        raise GtfsValidationError(f"{name} contains invalid YYYYMMDD dates")
    return parsed.dt.date


def _seconds(series: pd.Series) -> pd.Series:
    parts = series.str.split(":", expand=True)
    if parts.shape[1] != 3:
        return pd.Series(np.nan, index=series.index)
    numbers = parts.apply(pd.to_numeric, errors="coerce")
    return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]


def _unique_ids(frame: pd.DataFrame, column: str, name: str) -> None:
    if frame.empty:
        raise GtfsValidationError(f"{name} is empty")
    if frame[column].eq("").any():
        raise GtfsValidationError(f"{name}.{column} has blank values")
    if frame[column].duplicated().any():
        raise GtfsValidationError(f"{name}.{column} has duplicate values")


# --------------------------------------------------------------------------------------
# Feed reading
# --------------------------------------------------------------------------------------
@dataclass
class ReferenceData:
    tables: dict[Table, pd.DataFrame]
    feed_version: str | None
    feed_start_date: date | None
    feed_end_date: date | None


def read_feed(files: FeedFiles) -> ReferenceData:
    agency = files.read("agency.txt", ["agency_id", "agency_name", "agency_url"])
    if agency.empty:
        raise GtfsValidationError("agency.txt is empty")
    agency["agency_id"] = agency["agency_id"].where(agency["agency_id"] != "", "default")
    _unique_ids(agency, "agency_id", "agency")

    routes = files.read(
        "routes.txt",
        [
            "route_id",
            "agency_id",
            "route_short_name",
            "route_long_name",
            "route_type",
            "route_color",
            "route_text_color",
        ],
        required=("route_id", "route_type"),
    )
    _unique_ids(routes, "route_id", "routes")
    routes["route_type"] = _int(routes["route_type"], "routes.route_type")
    if routes["route_type"].isna().any():
        raise GtfsValidationError("routes.route_type is required")
    if len(agency) == 1:
        routes["agency_id"] = routes["agency_id"].where(routes["agency_id"] != "", agency["agency_id"].iloc[0])

    stops = files.read(
        "stops.txt",
        ["stop_id", "stop_code", "stop_name", "stop_lat", "stop_lon", "location_type", "parent_station"],
        required=("stop_id",),
    )
    _unique_ids(stops, "stop_id", "stops")
    stops["stop_lat"] = _float(stops["stop_lat"], "stops.stop_lat", -90, 90)
    stops["stop_lon"] = _float(stops["stop_lon"], "stops.stop_lon", -180, 180)
    stops["location_type"] = _int(stops["location_type"], "stops.location_type", {0, 1, 2, 3, 4})

    trips = files.read(
        "trips.txt",
        ["trip_id", "route_id", "service_id", "trip_headsign", "direction_id", "shape_id"],
        required=("trip_id", "route_id", "service_id"),
    )
    _unique_ids(trips, "trip_id", "trips")
    trips["direction_id"] = _int(trips["direction_id"], "trips.direction_id", {0, 1})
    orphans = ~trips["route_id"].isin(routes["route_id"])
    if orphans.mean() > MAX_ORPHAN_SHARE:
        raise GtfsValidationError("More than 1% of trips reference unknown routes")
    trips = trips[~orphans].copy()

    calendar = pd.DataFrame(columns=GTFS_CALENDAR.column_names)
    if "calendar.txt" in files:
        calendar = files.read(
            "calendar.txt", ["service_id", *WEEKDAYS, "start_date", "end_date"], required=("service_id",)
        )
        for day in WEEKDAYS:
            calendar[day] = _int(calendar[day], f"calendar.{day}", {0, 1}).fillna(0).astype(bool)
        calendar["start_date"] = _dates(calendar["start_date"], "calendar.start_date")
        calendar["end_date"] = _dates(calendar["end_date"], "calendar.end_date")
    calendar_dates = pd.DataFrame(columns=GTFS_CALENDAR_DATES.column_names)
    if "calendar_dates.txt" in files:
        raw = files.read(
            "calendar_dates.txt",
            ["service_id", "date", "exception_type"],
            required=("service_id", "date", "exception_type"),
        )
        calendar_dates = pd.DataFrame(
            {
                "service_id": raw["service_id"],
                "service_date": _dates(raw["date"], "calendar_dates.date"),
                "exception_type": _int(raw["exception_type"], "calendar_dates.exception_type", {1, 2}),
            }
        ).drop_duplicates(["service_id", "service_date"], keep="last")
    if calendar.empty and calendar_dates.empty:
        raise GtfsValidationError("Either calendar.txt or calendar_dates.txt must contain services")

    trips, route_stops, chosen_shapes = _schedule(files, trips)
    shapes = _shapes(files, chosen_shapes)

    feed_version = start = end = None
    if "feed_info.txt" in files:
        info = files.read("feed_info.txt", ["feed_version", "feed_start_date", "feed_end_date"])
        if not info.empty:
            row = info.iloc[0]
            feed_version = row["feed_version"] or None
            start = (
                _dates(pd.Series([row["feed_start_date"]]), "feed_start_date").iloc[0]
                if row["feed_start_date"]
                else None
            )
            end = _dates(pd.Series([row["feed_end_date"]]), "feed_end_date").iloc[0] if row["feed_end_date"] else None

    tables = {
        GTFS_AGENCY: agency,
        GTFS_ROUTES: routes.assign(
            agency_id=_null(routes["agency_id"]),
            route_short_name=_null(routes["route_short_name"]),
            route_long_name=_null(routes["route_long_name"]),
            route_color=_null(routes["route_color"]),
            route_text_color=_null(routes["route_text_color"]),
        ),
        GTFS_TRIPS: trips,
        GTFS_STOPS: stops.assign(
            stop_code=_null(stops["stop_code"]),
            stop_name=_null(stops["stop_name"]),
            parent_station=_null(stops["parent_station"]),
        ),
        GTFS_CALENDAR: calendar,
        GTFS_CALENDAR_DATES: calendar_dates,
        GTFS_ROUTE_STOPS: route_stops,
        GTFS_ROUTE_SHAPES: shapes,
    }
    return ReferenceData(tables, feed_version, start, end)


def _schedule(files: FeedFiles, trips: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    times = files.read(
        "stop_times.txt",
        ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
        required=("trip_id", "stop_id", "stop_sequence"),
    )
    times = times[times["trip_id"].isin(trips["trip_id"])].copy()
    if times.empty:
        raise GtfsValidationError("stop_times.txt has no rows for known trips")
    times["stop_sequence"] = _int(times["stop_sequence"], "stop_times.stop_sequence")
    times["arrival"] = _seconds(times["arrival_time"])
    times["departure"] = _seconds(times["departure_time"])
    times = times.sort_values(["trip_id", "stop_sequence"], kind="stable")

    grouped = times.groupby("trip_id", sort=False)
    first = grouped.head(1).set_index("trip_id")
    last = grouped.tail(1).set_index("trip_id")
    summary = pd.DataFrame(
        {
            "first_departure_sec": first["departure"].fillna(first["arrival"]),
            "last_arrival_sec": last["arrival"].fillna(last["departure"]),
            "stop_count": grouped.size(),
            "first_stop_id": first["stop_id"],
            "last_stop_id": last["stop_id"],
        }
    )
    trips = trips.join(summary, on="trip_id")
    for column in ("first_departure_sec", "last_arrival_sec", "stop_count"):
        trips[column] = trips[column].round().astype("Int64")
    trips = trips.assign(trip_headsign=_null(trips["trip_headsign"]), shape_id=_null(trips["shape_id"]))

    # The dominant stop pattern of every route direction
    patterns = grouped["stop_id"].agg("|".join).rename("pattern")
    keyed = trips[["trip_id", "route_id", "direction_id", "shape_id"]].join(patterns, on="trip_id")
    keyed = keyed.dropna(subset=["pattern"])
    keyed["direction_id"] = keyed["direction_id"].fillna(-1).astype(int)
    counts = keyed.groupby(["route_id", "direction_id", "pattern"]).size().rename("trip_count").reset_index()
    counts["length"] = counts["pattern"].str.count(r"\|") + 1
    best = counts.sort_values(
        ["route_id", "direction_id", "trip_count", "length"], ascending=[True, True, False, False]
    ).drop_duplicates(["route_id", "direction_id"])
    rows = []
    for record in best.itertuples(index=False):
        for order, stop_id in enumerate(str(record.pattern).split("|"), start=1):
            rows.append((record.route_id, record.direction_id, order, stop_id, int(record.trip_count)))
    route_stops = pd.DataFrame(rows, columns=GTFS_ROUTE_STOPS.column_names)

    shapes = keyed.dropna(subset=["shape_id"])
    chosen = (
        shapes.groupby(["route_id", "direction_id", "shape_id"])
        .size()
        .rename("n")
        .reset_index()
        .sort_values(["route_id", "direction_id", "n"], ascending=[True, True, False])
        .drop_duplicates(["route_id", "direction_id"])
    )
    return trips[GTFS_TRIPS.column_names], route_stops, chosen


def _shapes(files: FeedFiles, chosen: pd.DataFrame) -> pd.DataFrame:
    empty = pd.DataFrame(columns=GTFS_ROUTE_SHAPES.column_names)
    if chosen.empty or "shapes.txt" not in files:
        return empty
    points = files.read(
        "shapes.txt",
        ["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"],
        required=("shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"),
    )
    points = points[points["shape_id"].isin(chosen["shape_id"])].copy()
    points["lat"] = _float(points["shape_pt_lat"], "shapes.shape_pt_lat", -90, 90)
    points["lon"] = _float(points["shape_pt_lon"], "shapes.shape_pt_lon", -180, 180)
    points["seq"] = _int(points["shape_pt_sequence"], "shapes.shape_pt_sequence")
    points = points.sort_values(["shape_id", "seq"])
    by_shape = {shape: frame for shape, frame in points.groupby("shape_id", sort=False)}  # noqa: C416
    rows = []
    for record in chosen.itertuples(index=False):
        frame = by_shape.get(record.shape_id)
        if frame is None or frame.empty:
            continue
        keep = np.unique(np.linspace(0, len(frame) - 1, min(len(frame), MAX_SHAPE_POINTS)).round().astype(int))
        for order, (lat, lon) in enumerate(frame[["lat", "lon"]].to_numpy()[keep], start=1):
            rows.append((record.route_id, int(record.direction_id), record.shape_id, order, float(lat), float(lon)))
    return pd.DataFrame(rows, columns=GTFS_ROUTE_SHAPES.column_names) if rows else empty


# --------------------------------------------------------------------------------------
# Download and load
# --------------------------------------------------------------------------------------
@dataclass
class Download:
    path: Path | None
    etag: str | None
    last_modified: str | None
    not_modified: bool = False


def download(url: str, folder: Path, etag: str | None, last_modified: str | None, timeout: float) -> Download:
    headers = {"User-Agent": f"bus-checker/{__version__}"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    target = folder / "gtfs.zip"
    with requests.get(url, headers=headers, stream=True, timeout=(10, timeout)) as response:
        if response.status_code == 304:
            return Download(None, etag, last_modified, not_modified=True)
        response.raise_for_status()
        with open(target, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                handle.write(chunk)
        return Download(target, response.headers.get("ETag"), response.headers.get("Last-Modified"))


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    if path.is_dir():
        for member in sorted(path.rglob("*.txt")):
            digest.update(member.name.encode())
            digest.update(member.read_bytes())
        return digest.hexdigest()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _frame_rows(table: Table, frame: pd.DataFrame) -> list[tuple]:
    ordered = frame[table.column_names].astype(object).where(frame[table.column_names].notna(), None)
    return [tuple(row) for row in ordered.itertuples(index=False, name=None)]


def replace_reference(warehouse: Warehouse, data: ReferenceData) -> dict[str, int]:
    counts = {}
    for table, frame in data.tables.items():
        rows = _frame_rows(table, frame)
        warehouse.execute(f"DELETE FROM {table.ref}")
        if rows:
            warehouse.stage("bus_stage_gtfs", table.columns, rows)
            columns = ", ".join(quote_identifier(c) for c in table.column_names)
            warehouse.execute(f"INSERT INTO {table.ref} ({columns}) SELECT {columns} FROM bus_stage_gtfs")
            warehouse.drop_stage("bus_stage_gtfs")
        counts[table.name] = len(rows)
    return counts


def _last_load(warehouse: Warehouse) -> dict[str, Any] | None:
    rows = warehouse.fetchall(
        f"SELECT finished_at, sha256, etag, last_modified FROM {GTFS_LOADS.ref} "
        "WHERE status IN ('success', 'unchanged') ORDER BY finished_at DESC LIMIT 1"
    )
    if not rows:
        return None
    finished, sha, etag, modified = rows[0]
    last_success = warehouse.scalar(
        f"SELECT sha256 FROM {GTFS_LOADS.ref} WHERE status = 'success' ORDER BY finished_at DESC LIMIT 1"
    )
    return {"finished_at": finished, "sha256": last_success or sha, "etag": etag, "last_modified": modified}


def _record(warehouse: Warehouse, values: dict[str, Any]) -> None:
    columns = GTFS_LOADS.column_names
    record = {c: values.get(c) for c in columns}
    names = ", ".join(quote_identifier(c) for c in columns)
    warehouse.execute(
        f"INSERT INTO {GTFS_LOADS.ref} ({names}) VALUES ({', '.join(':' + c for c in columns)})",
        record,
    )


def refresh_gtfs(
    settings: Settings, *, force: bool = False, if_due: bool = False, source: str | None = None
) -> GtfsOutcome:
    started = datetime.now(UTC)
    load_id = new_uuid()
    origin = source or settings.gtfs_url
    ensure_ready(settings)
    with session(settings) as warehouse:
        last = _last_load(warehouse)
    if if_due and not force and last is not None:
        age = started - last["finished_at"]
        if age < timedelta(hours=settings.gtfs_refresh_hours):
            return GtfsOutcome("skipped", message=f"Refreshed {age} ago")

    audit: dict[str, Any] = {"load_id": load_id, "started_at": started, "source": origin}
    try:
        with tempfile.TemporaryDirectory(prefix="bus-gtfs-") as folder:
            if origin.startswith(("http://", "https://")):
                fetched = download(
                    origin,
                    Path(folder),
                    None if force or last is None else last["etag"],
                    None if force or last is None else last["last_modified"],
                    timeout=max(settings.http_timeout, 120),
                )
                if fetched.not_modified:
                    return _unchanged(settings, audit, last, "HTTP 304 Not Modified")
                assert fetched.path is not None
                path = fetched.path
                audit.update(etag=fetched.etag, last_modified=fetched.last_modified)
            else:
                path = Path(origin)
                if not path.exists():
                    raise FileNotFoundError(origin)
            sha = _sha256_file(path)
            audit["sha256"] = sha
            if not force and last is not None and last["sha256"] == sha:
                return _unchanged(settings, audit, last, "Feed content unchanged")
            files = FeedFiles(path)
            try:
                data = read_feed(files)
            finally:
                files.close()
        with session(settings) as warehouse:
            counts = replace_reference(warehouse, data)
            _record(
                warehouse,
                {
                    **audit,
                    "finished_at": datetime.now(UTC),
                    "status": "success",
                    "feed_version": data.feed_version,
                    "feed_start_date": data.feed_start_date,
                    "feed_end_date": data.feed_end_date,
                    "row_counts": json.dumps(counts, sort_keys=True),
                },
            )
    except Exception as error:
        with session(settings) as warehouse:
            _record(
                warehouse,
                {
                    **audit,
                    "finished_at": datetime.now(UTC),
                    "status": "failed",
                    "error_message": f"{type(error).__name__}: {error}"[:500],
                },
            )
        raise
    logger.info("GTFS reference loaded: %s", counts)
    return GtfsOutcome("success", load_id, audit.get("sha256"), data.feed_version, counts)


def _unchanged(settings: Settings, audit: dict[str, Any], last: dict[str, Any] | None, message: str) -> GtfsOutcome:
    with session(settings) as warehouse:
        _record(
            warehouse,
            {
                **audit,
                "sha256": audit.get("sha256") or (last or {}).get("sha256"),
                "etag": audit.get("etag") or (last or {}).get("etag"),
                "last_modified": audit.get("last_modified") or (last or {}).get("last_modified"),
                "finished_at": datetime.now(UTC),
                "status": "unchanged",
                "error_message": message,
            },
        )
    logger.info("GTFS reference unchanged: %s", message)
    return GtfsOutcome("unchanged", audit["load_id"], audit.get("sha256"), message=message)


def zip_directory(directory: Path) -> bytes:
    """Build an in-memory GTFS zip from a folder of .txt files (used by test fixtures)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for member in sorted(directory.glob("*.txt")):
            archive.write(member, member.name)
    return buffer.getvalue()
