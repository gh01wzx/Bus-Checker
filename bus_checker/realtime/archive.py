"""Compressed archive of raw API responses.

Raw payloads are kept as files rather than database rows: a single trip-update snapshot
is ~0.7 MB of JSON, ~200 MB per day. Files compress ~10x, are trivial to prune, and can
be replayed with ``python -m bus_checker replay``.
"""

from __future__ import annotations

import contextlib
import gzip
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bus_checker.realtime import FEEDS

logger = logging.getLogger(__name__)


def archive_path(base: Path, feed: str, received_at: datetime, sha256: str) -> Path:
    moment = received_at.astimezone(UTC)
    return (
        base
        / feed
        / f"{moment:%Y}"
        / f"{moment:%m}"
        / f"{moment:%d}"
        / f"{moment:%Y%m%dT%H%M%SZ}-{sha256[:12]}.json.gz"
    )


def write_archive(base: Path, feed: str, received_at: datetime, sha256: str, content: bytes) -> Path:
    path = archive_path(base, feed, received_at, sha256)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "wb") as handle:
        with gzip.GzipFile(fileobj=handle, mode="wb", compresslevel=6, mtime=0) as archive:
            archive.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return path


def read_archive(path: Path) -> bytes:
    data = path.read_bytes()
    if data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    return data


def infer_feed(path: Path) -> str | None:
    for part in path.parts:
        if part in FEEDS:
            return part
    name = path.name.lower()
    for feed, hints in {
        "trip_updates": ("tripupdate", "trip_update"),
        "vehicle_positions": ("vehicle",),
        "service_alerts": ("alert",),
    }.items():
        if any(hint in name for hint in hints):
            return feed
    return None


def received_time(path: Path) -> datetime:
    """Recover the receive time from an archive file name, falling back to its mtime."""
    stem = path.name.split("-", 1)[0]
    try:
        return datetime.strptime(stem, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC)


def purge_archive(base: Path, retention_days: int, now: datetime | None = None) -> int:
    """Delete archive files older than the retention window. 0 keeps everything."""
    if retention_days <= 0 or not base.exists():
        return 0
    cutoff = ((now or datetime.now(UTC)) - timedelta(days=retention_days)).timestamp()
    removed = 0
    for path in base.rglob("*.json.gz"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except FileNotFoundError:
            continue
    for directory in sorted((p for p in base.rglob("*") if p.is_dir()), reverse=True):
        with contextlib.suppress(OSError):  # rmdir only succeeds on empty directories
            directory.rmdir()
    # Leftover temporary files from an interrupted write
    for path in base.rglob("*.tmp"):
        if path.stat().st_mtime < time.time() - 3600:
            path.unlink(missing_ok=True)
    logger.info("Archive purge removed %s files older than %s days", removed, retention_days)
    return removed
