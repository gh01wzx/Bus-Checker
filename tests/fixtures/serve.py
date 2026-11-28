"""Fixture HTTP server for the Docker stack test: AT-shaped feeds relative to the current
time, and a GTFS zip built from tests/fixtures/gtfs."""

from __future__ import annotations

import io
import json
import sys
import zipfile
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import feeds  # noqa: E402


def gtfs_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for member in sorted((HERE / "gtfs").glob("*.txt")):
            archive.write(member, member.name)
    return buffer.getvalue()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        now = datetime.now(UTC)
        routes = {
            "/tripupdates": lambda: json.dumps(feeds.trip_updates(now)).encode(),
            "/vehiclelocations": lambda: json.dumps(feeds.vehicle_positions(now)).encode(),
            "/servicealerts": lambda: json.dumps(feeds.service_alerts(now)).encode(),
            "/gtfs.zip": gtfs_zip,
        }
        if self.path not in routes:
            self.send_error(404)
            return
        if self.path != "/gtfs.zip" and self.headers.get("Ocp-Apim-Subscription-Key") != "fixture-only":
            self.send_error(401)
            return
        body = routes[self.path]()
        self.send_response(200)
        self.send_header("Content-Type", "application/zip" if self.path.endswith(".zip") else "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write(f"fixture: {format % args}\n")


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
