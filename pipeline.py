import argparse
import json
import logging
import sys
from pathlib import Path

from bus_checker.database import connect
from bus_checker.ingestion import collect_burst, run_pipeline


def main():
    parser = argparse.ArgumentParser(description="Bus Checker data commands")
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("collect", help="Collect live data or replay a feed")
    source = collect.add_mutually_exclusive_group()
    source.add_argument("--file", type=Path, help="Load an archived JSON feed")
    source.add_argument("--replay", help="Replay an existing batch ID")
    source.add_argument(
        "--burst", action="store_true", help="Collect five times, five minutes apart"
    )
    build_command = commands.add_parser("build", help="Build SQL models and run data tests")
    build_command.add_argument("--full-refresh", action="store_true")
    build_command.add_argument(
        "--docs", action="store_true", help="Generate dbt documentation"
    )
    commands.add_parser("load-gtfs", help="Refresh route and stop reference data")
    commands.add_parser("import-history", help="Import existing trip history")

    arguments = sys.argv[1:]
    if not arguments or arguments[0].split("=", 1)[0] in {"--file", "--replay"}:
        arguments = ["collect", *arguments]
    args = parser.parse_args(arguments)
    logging.basicConfig(level=logging.INFO)

    if args.command == "collect":
        if args.burst:
            collect_burst()
            return
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
    elif args.command == "build":
        from bus_checker.build import build

        build(args.full_refresh, args.docs)
    elif args.command == "load-gtfs":
        from bus_checker.reference import load_gtfs

        load_gtfs()
    elif args.command == "import-history":
        from bus_checker.reference import import_history

        import_history()


if __name__ == "__main__":
    main()
