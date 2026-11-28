"""Fetch, archive, parse and load realtime feeds with a full audit trail.

Each feed is loaded in its own transaction: accepted rows, quarantined records and the
fetch-run audit row commit together or not at all. A failure in one feed never discards
another feed's data.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bus_checker.config import Settings
from bus_checker.ids import canonical_json, new_uuid, sha256_hex, stable_uuid
from bus_checker.realtime import FEEDS
from bus_checker.realtime.archive import infer_feed, read_archive, received_time, write_archive
from bus_checker.realtime.client import Fetched, FetchError, fetch_feed, make_session
from bus_checker.realtime.parsing import PARSERS, ParsedFeed
from bus_checker.schema import (
    FETCH_RUNS,
    QUARANTINE,
    SERVICE_ALERT_ENTITIES,
    SERVICE_ALERTS,
    TRIP_UPDATES,
    VEHICLE_POSITIONS,
    Table,
    ensure_ready,
)
from bus_checker.warehouse import Warehouse, quote_identifier, session

logger = logging.getLogger(__name__)
MAX_QUARANTINE_RECORD_CHARS = 20_000
MAX_ERROR_CHARS = 500
LOADED_STATUSES = ("success", "warning", "empty")


@dataclass
class FetchOutcome:
    feed: str
    fetch_id: str
    status: str
    source: str
    feed_ts: str | None = None
    entities: int = 0
    rows_parsed: int = 0
    rows_inserted: int = 0
    rows_duplicate: int = 0
    rows_rejected: int = 0
    error: str | None = None

    @property
    def failed(self) -> bool:
        return self.status == "failed"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> datetime:
    return datetime.now(UTC)


def _row_values(table: Table, row: dict[str, Any], extra: dict[str, Any]) -> tuple:
    return tuple(extra[c] if c in extra else row.get(c) for c in table.column_names)


def insert_new_rows(
    warehouse: Warehouse,
    table: Table,
    rows: Sequence[dict[str, Any]],
    key: str,
    extra: dict[str, Any],
) -> int:
    """Insert rows whose key is not already present in the same service-date range."""
    if not rows:
        return 0
    values = [_row_values(table, row, extra) for row in rows]
    warehouse.stage("bus_stage_rows", table.columns, values)
    dates = [row["service_date"] for row in rows]
    columns = ", ".join(quote_identifier(c) for c in table.column_names)
    k = quote_identifier(key)
    inserted = warehouse.execute(
        f"INSERT INTO {table.ref} ({columns}) SELECT {columns} FROM bus_stage_rows AS s "
        f"WHERE NOT EXISTS (SELECT 1 FROM {table.ref} AS t "
        f"WHERE t.service_date BETWEEN :low AND :high AND t.{k} = s.{k})",
        {"low": min(dates), "high": max(dates)},
    )
    warehouse.drop_stage("bus_stage_rows")
    return inserted


def upsert_alerts(warehouse: Warehouse, parsed: ParsedFeed, fetch_id: str, seen_at: datetime) -> int:
    """Record new alert versions and refresh ``last_seen_at`` on known ones."""
    if not parsed.rows:
        return 0
    extra = {"first_seen_at": seen_at, "last_seen_at": seen_at, "last_fetch_id": fetch_id}
    warehouse.stage(
        "bus_stage_alerts",
        SERVICE_ALERTS.columns,
        [_row_values(SERVICE_ALERTS, row, extra) for row in parsed.rows],
    )
    warehouse.stage(
        "bus_stage_alert_entities",
        SERVICE_ALERT_ENTITIES.columns,
        [_row_values(SERVICE_ALERT_ENTITIES, row, {}) for row in parsed.children],
    )
    known = f"SELECT 1 FROM {SERVICE_ALERTS.ref} AS a WHERE a.alert_version_id = s.alert_version_id"
    new_versions = warehouse.scalar(f"SELECT count(*) FROM bus_stage_alerts AS s WHERE NOT EXISTS ({known})")
    entity_columns = ", ".join(quote_identifier(c) for c in SERVICE_ALERT_ENTITIES.column_names)
    warehouse.execute(
        f"INSERT INTO {SERVICE_ALERT_ENTITIES.ref} ({entity_columns}) "
        f"SELECT {entity_columns} FROM bus_stage_alert_entities AS s WHERE NOT EXISTS ({known})"
    )
    columns = ", ".join(quote_identifier(c) for c in SERVICE_ALERTS.column_names)
    warehouse.execute(
        f"INSERT INTO {SERVICE_ALERTS.ref} ({columns}) SELECT {columns} FROM bus_stage_alerts "
        "ON CONFLICT (alert_version_id) DO UPDATE SET "
        "last_seen_at = EXCLUDED.last_seen_at, last_fetch_id = EXCLUDED.last_fetch_id, "
        "active_at_last_seen = EXCLUDED.active_at_last_seen"
    )
    warehouse.drop_stage("bus_stage_alerts")
    warehouse.drop_stage("bus_stage_alert_entities")
    return int(new_versions or 0)


def load_parsed(warehouse: Warehouse, parsed: ParsedFeed, fetch_id: str, ingested_at: datetime) -> int:
    extra = {"fetch_id": fetch_id, "ingested_at": ingested_at}
    if parsed.feed == "trip_updates":
        return insert_new_rows(warehouse, TRIP_UPDATES, parsed.rows, "update_id", extra)
    if parsed.feed == "vehicle_positions":
        return insert_new_rows(warehouse, VEHICLE_POSITIONS, parsed.rows, "position_id", extra)
    if parsed.feed == "service_alerts":
        return upsert_alerts(warehouse, parsed, fetch_id, ingested_at)
    raise ValueError(f"Unknown feed {parsed.feed}")


def write_quarantine(
    warehouse: Warehouse, feed: str, fetch_id: str, rejects: Sequence[tuple[str, Any]], at: datetime
) -> None:
    if not rejects:
        return
    rows = [
        (
            stable_uuid("rejection", fetch_id, index),
            fetch_id,
            feed,
            reason,
            canonical_json(record)[:MAX_QUARANTINE_RECORD_CHARS],
            at,
        )
        for index, (reason, record) in enumerate(rejects)
    ]
    warehouse.stage("bus_stage_quarantine", QUARANTINE.columns, rows)
    columns = ", ".join(quote_identifier(c) for c in QUARANTINE.column_names)
    warehouse.execute(f"INSERT INTO {QUARANTINE.ref} ({columns}) SELECT {columns} FROM bus_stage_quarantine")
    warehouse.drop_stage("bus_stage_quarantine")


def write_run(warehouse: Warehouse, values: dict[str, Any]) -> None:
    columns = FETCH_RUNS.column_names
    record = {column: values.get(column) for column in columns}
    names = ", ".join(quote_identifier(c) for c in columns)
    slots = ", ".join(f":{c}" for c in columns)
    warehouse.execute(f"INSERT INTO {FETCH_RUNS.ref} ({names}) VALUES ({slots})", record)


def last_loaded_sha(warehouse: Warehouse, feed: str) -> str | None:
    statuses = ", ".join(f"'{s}'" for s in (*LOADED_STATUSES, "unchanged"))
    return warehouse.scalar(
        f"SELECT payload_sha256 FROM {FETCH_RUNS.ref} WHERE feed = :feed "
        f"AND status IN ({statuses}) ORDER BY started_at DESC LIMIT 1",
        {"feed": feed},
    )


def ingest_payload(
    settings: Settings,
    feed: str,
    content: bytes,
    received_at: datetime,
    *,
    source: str,
    run_id: str | None = None,
    http_status: int | None = None,
    archive: bool = True,
    skip_unchanged: bool = True,
    started_at: datetime | None = None,
) -> FetchOutcome:
    fetch_id = new_uuid()
    started = started_at or _now()
    sha = sha256_hex(content)
    audit: dict[str, Any] = {
        "fetch_id": fetch_id,
        "run_id": run_id,
        "feed": feed,
        "source": source,
        "started_at": started,
        "http_status": http_status,
        "payload_bytes": len(content),
        "payload_sha256": sha,
    }
    outcome = FetchOutcome(feed=feed, fetch_id=fetch_id, status="failed", source=source)
    try:
        ensure_ready(settings)
        with session(settings) as warehouse:
            if skip_unchanged and last_loaded_sha(warehouse, feed) == sha:
                outcome.status = "unchanged"
                write_run(warehouse, {**audit, "status": "unchanged", "finished_at": _now()})
                logger.info("%s unchanged since the previous fetch", feed)
                return outcome

            parsed = PARSERS[feed](json.loads(content), received_at)
            archived = None
            if archive and settings.archive_dir is not None:
                try:
                    archived = write_archive(settings.archive_dir, feed, received_at, sha, content)
                except OSError as error:  # Never lose a load because the archive disk is full
                    logger.warning("Could not archive %s payload: %s", feed, error)

            ingested_at = _now()
            inserted = load_parsed(warehouse, parsed, fetch_id, ingested_at)
            write_quarantine(warehouse, feed, fetch_id, parsed.rejects, ingested_at)
            rows = len(parsed.rows)
            status = "empty" if parsed.entity_count == 0 else ("warning" if parsed.rejects else "success")
            outcome.status = status
            outcome.feed_ts = parsed.feed_ts.isoformat()
            outcome.entities = parsed.entity_count
            outcome.rows_parsed = rows
            outcome.rows_inserted = inserted
            outcome.rows_duplicate = parsed.duplicates + max(rows - inserted, 0)
            outcome.rows_rejected = len(parsed.rejects)
            write_run(
                warehouse,
                {
                    **audit,
                    "finished_at": _now(),
                    "status": status,
                    "feed_ts": parsed.feed_ts,
                    "entity_count": parsed.entity_count,
                    "rows_parsed": rows,
                    "rows_inserted": inserted,
                    "rows_duplicate": outcome.rows_duplicate,
                    "rows_rejected": outcome.rows_rejected,
                    "archive_path": str(archived) if archived else None,
                },
            )
    except Exception as error:
        outcome.error = f"{type(error).__name__}: {error}"[:MAX_ERROR_CHARS]
        logger.error("%s ingestion failed: %s", feed, outcome.error)
        record_failure(settings, audit, error)
        return outcome
    logger.info(
        "%s %s: entities=%s parsed=%s inserted=%s duplicate=%s rejected=%s",
        feed,
        outcome.status,
        outcome.entities,
        outcome.rows_parsed,
        outcome.rows_inserted,
        outcome.rows_duplicate,
        outcome.rows_rejected,
    )
    return outcome


def record_failure(settings: Settings, audit: dict[str, Any], error: BaseException) -> None:
    status_code = getattr(error, "status_code", None)
    try:
        ensure_ready(settings)
        with session(settings) as warehouse:
            write_run(
                warehouse,
                {
                    **audit,
                    "http_status": audit.get("http_status") or status_code,
                    "finished_at": _now(),
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "error_message": str(error)[:MAX_ERROR_CHARS],
                },
            )
    except Exception:
        logger.exception("Could not persist the failed-run audit record")


def collect(settings: Settings, feeds: Iterable[str] = FEEDS, run_id: str | None = None) -> list[FetchOutcome]:
    """Fetch the requested feeds concurrently, then load them one at a time."""
    feeds = list(dict.fromkeys(feeds))
    unknown = set(feeds) - set(FEEDS)
    if unknown:
        raise ValueError(f"Unknown feed(s): {', '.join(sorted(unknown))}")
    settings.require_api_key()
    ensure_ready(settings)

    started = {feed: _now() for feed in feeds}
    http = make_session(settings)
    outcomes: list[FetchOutcome] = []
    try:
        with ThreadPoolExecutor(max_workers=len(feeds), thread_name_prefix="fetch") as pool:
            futures = {feed: pool.submit(fetch_feed, http, settings, feed) for feed in feeds}
            for feed in feeds:
                try:
                    fetched: Fetched = futures[feed].result()
                except FetchError as error:
                    audit = {
                        "fetch_id": new_uuid(),
                        "run_id": run_id,
                        "feed": feed,
                        "source": "api",
                        "started_at": started[feed],
                        "http_status": error.status_code,
                    }
                    record_failure(settings, audit, error)
                    outcomes.append(
                        FetchOutcome(
                            feed=feed,
                            fetch_id=audit["fetch_id"],
                            status="failed",
                            source="api",
                            error=str(error),
                        )
                    )
                    logger.error("%s fetch failed: %s", feed, error)
                    continue
                outcomes.append(
                    ingest_payload(
                        settings,
                        feed,
                        fetched.content,
                        fetched.received_at,
                        source="api",
                        run_id=run_id,
                        http_status=fetched.status_code,
                        started_at=started[feed],
                    )
                )
    finally:
        http.close()
    return outcomes


def replay(
    settings: Settings, paths: Iterable[Path], feed: str | None = None, run_id: str | None = None
) -> list[FetchOutcome]:
    """Load archived (``.json.gz``) or plain JSON payloads. Safe to repeat."""
    ensure_ready(settings)
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob("*") if p.suffix in {".json", ".gz"}))
        else:
            files.append(path)
    outcomes = []
    for path in sorted(files, key=received_time):
        name = feed or infer_feed(path)
        if name not in FEEDS:
            raise ValueError(f"Cannot infer the feed for {path}; pass --feed")
        outcomes.append(
            ingest_payload(
                settings,
                name,
                read_archive(path),
                received_time(path),
                source="replay",
                run_id=run_id,
                archive=False,
                skip_unchanged=False,
            )
        )
    return outcomes
