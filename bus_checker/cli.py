"""Command line interface: ``python -m bus_checker <command>``.

Every command prints a JSON summary on stdout and logs progress on stderr. A non-zero exit
code means the step failed and should be retried or investigated.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from bus_checker import __version__
from bus_checker.config import ConfigError, Settings
from bus_checker.realtime import FEEDS

logger = logging.getLogger("bus_checker")


def _print(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))


def _settings() -> Settings:
    return Settings.from_env()


def cmd_init(args: argparse.Namespace) -> int:
    from bus_checker.schema import ensure_schema
    from bus_checker.warehouse import session

    settings = _settings()
    with session(settings) as warehouse:
        ensure_schema(warehouse)
    _print({"backend": settings.backend, "status": "ready"})
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    from bus_checker.realtime.collector import collect

    outcomes = collect(_settings(), args.feed or FEEDS, run_id=args.run_id)
    _print([o.as_dict() for o in outcomes])
    return 1 if any(o.failed for o in outcomes) else 0


def cmd_replay(args: argparse.Namespace) -> int:
    from bus_checker.realtime.collector import replay

    outcomes = replay(_settings(), [Path(p) for p in args.paths], feed=args.feed, run_id=args.run_id)
    _print([o.as_dict() for o in outcomes])
    return 1 if any(o.failed for o in outcomes) else 0


def cmd_gtfs(args: argparse.Namespace) -> int:
    from bus_checker.gtfs import refresh_gtfs

    outcome = refresh_gtfs(_settings(), force=args.force, if_due=args.if_due, source=args.source)
    _print(outcome.as_dict())
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    from bus_checker.transform import BuildFailed, build

    try:
        summary = build(
            _settings(),
            full_refresh=args.full_refresh,
            full_tests=args.full_tests,
            select=args.select,
        )
    except BuildFailed as error:
        _print(error.summary.as_dict())
        return 1
    _print(summary.as_dict())
    return 0


def cmd_docs(args: argparse.Namespace) -> int:
    from bus_checker.transform import generate_docs

    summary = generate_docs(_settings())
    _print(summary.as_dict())
    return 0 if summary.status == "success" else 1


def cmd_publish_snapshot(args: argparse.Namespace) -> int:
    from bus_checker.publish.snapshot import publish_snapshot

    _print(publish_snapshot(_settings()))
    return 0


def cmd_sync_remote(args: argparse.Namespace) -> int:
    from bus_checker.publish.remote import sync_remote

    result = sync_remote(_settings(), full=args.full)
    _print({k: v for k, v in result.items() if k != "tables"} | {"tables": len(result["tables"])})
    return 0


def cmd_maintain(args: argparse.Namespace) -> int:
    from bus_checker.maintenance import maintain

    _print(maintain(_settings()))
    return 0


def cmd_run_once(args: argparse.Namespace) -> int:
    """Collect, refresh GTFS when due, build and publish: one scheduler tick without Airflow."""
    from bus_checker.gtfs import refresh_gtfs
    from bus_checker.publish.snapshot import publish_snapshot
    from bus_checker.realtime.collector import collect
    from bus_checker.transform import BuildFailed, build

    settings = _settings()
    report: dict[str, Any] = {}
    outcomes = collect(settings, FEEDS)
    report["collect"] = [o.as_dict() for o in outcomes]
    try:
        report["gtfs"] = refresh_gtfs(settings, if_due=True).as_dict()
    except Exception as error:
        logger.error("GTFS refresh failed: %s", error)
        report["gtfs"] = {"status": "failed", "error": str(error)}
    try:
        report["build"] = build(settings).as_dict()
    except BuildFailed as error:
        report["build"] = error.summary.as_dict()
        _print(report)
        return 1
    if settings.backend == "duckdb":
        report["snapshot"] = publish_snapshot(settings)
    _print(report)
    return 1 if any(o.failed for o in outcomes) else 0


def cmd_status(args: argparse.Namespace) -> int:
    from bus_checker.schema import FETCH_RUNS, TRIP_UPDATES, VEHICLE_POSITIONS
    from bus_checker.warehouse import session

    settings = _settings()
    status: dict[str, Any] = {"version": __version__, "backend": settings.backend}
    with session(settings, read_only=True) as warehouse:
        for table in (TRIP_UPDATES, VEHICLE_POSITIONS):
            status[f"{table.name}_rows"] = warehouse.scalar(f"SELECT count(*) FROM {table.ref}")
        status["latest_fetches"] = [
            dict(zip(("feed", "status", "started_at", "rows_inserted"), row, strict=True))
            for row in warehouse.fetchall(
                f"SELECT feed, status, started_at, rows_inserted FROM ("
                f"SELECT feed, status, started_at, rows_inserted, row_number() over "
                f"(partition by feed order by started_at desc) AS rn FROM {FETCH_RUNS.ref}) AS r "
                "WHERE rn = 1 ORDER BY feed"
            )
        ]
    if settings.backend == "duckdb" and settings.snapshot_path.exists():
        status["snapshot_bytes"] = settings.snapshot_path.stat().st_size
    _print(status)
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="bus_checker", description=__doc__)
    root.add_argument("--version", action="version", version=__version__)
    sub = root.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create warehouse schemas and tables").set_defaults(func=cmd_init)

    collect = sub.add_parser("collect", help="Fetch and load the AT realtime feeds")
    collect.add_argument("--feed", action="append", choices=FEEDS, help="Limit to a feed (repeatable)")
    collect.add_argument("--run-id", help="Orchestrator run id for the audit trail")
    collect.set_defaults(func=cmd_collect)

    replay = sub.add_parser("replay", help="Load archived payload files (.json or .json.gz)")
    replay.add_argument("paths", nargs="+", help="Files or directories")
    replay.add_argument("--feed", choices=FEEDS, help="Feed name when it cannot be inferred")
    replay.add_argument("--run-id")
    replay.set_defaults(func=cmd_replay)

    gtfs = sub.add_parser("gtfs", help="Refresh GTFS static reference data")
    gtfs.add_argument("--if-due", action="store_true", help="Skip when refreshed recently")
    gtfs.add_argument("--force", action="store_true", help="Reload even if unchanged")
    gtfs.add_argument("--source", help="URL, zip file or directory instead of AT_GTFS_URL")
    gtfs.set_defaults(func=cmd_gtfs)

    build = sub.add_parser("build", help="Run dbt build (models and data tests)")
    build.add_argument("--full-refresh", action="store_true")
    build.add_argument("--full-tests", action="store_true", help="Test the full history")
    build.add_argument("--select", help="dbt node selection")
    build.set_defaults(func=cmd_build)

    sub.add_parser("docs", help="Generate dbt documentation").set_defaults(func=cmd_docs)
    sub.add_parser("publish-snapshot", help="Publish the DuckDB dashboard snapshot").set_defaults(
        func=cmd_publish_snapshot
    )
    sync = sub.add_parser("sync-remote", help="Publish marts to BUS_PUBLISH_URL")
    sync.add_argument("--full", action="store_true", help="Recreate and republish every table")
    sync.set_defaults(func=cmd_sync_remote)
    sub.add_parser("maintain", help="Apply retention and vacuum").set_defaults(func=cmd_maintain)
    sub.add_parser("run-once", help="collect + gtfs (if due) + build + publish").set_defaults(func=cmd_run_once)
    sub.add_parser("status", help="Show warehouse status").set_defaults(func=cmd_status)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("BUS_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as error:
        logger.error("Configuration error: %s", error)
        return 2
    except Exception:
        logger.exception("Command %s failed", args.command)
        return 1
