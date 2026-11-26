"""Serve the same tiny AT feed to both Docker integration jobs."""

import io
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from zipfile import ZipFile


def reference_zip():
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("routes.txt", "route_id,route_short_name,route_type\n101,101,3\n")
        archive.writestr("trips.txt", "route_id,trip_headsign,direction_id\n101,City,0\n")
        archive.writestr("stops.txt", "stop_id,stop_name,stop_lat,stop_lon\n001,Test,-36.8,174.7\n")
    return output.getvalue()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/gtfs.zip":
            body = reference_zip()
        elif self.path == "/trips":
            update = {
                "trip": {"route_id": "101", "trip_id": "trip-1", "direction_id": 0},
                "delay": 90,
                "stop_time_update": [{"stop_id": "001", "arrival": {"delay": 90}}],
            }
            body = json.dumps({
                "header": {"timestamp": 1783396800}, "entity": [{"trip_update": update}]
            }).encode()
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
