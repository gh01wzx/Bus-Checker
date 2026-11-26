import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from bus_checker.database import read_frame
from bus_checker.reference import download_and_extract_gtfs, load_gtfs


class GtfsDownloadTests(unittest.TestCase):
    def test_invalid_refresh_preserves_reference_tables_and_refresh_time(self):
        valid_stop = "001,City,-36.8,174.7\n"
        stops = valid_stop
        route = "A"

        def write_feed(folder):
            (folder / "routes.txt").write_text(
                f"route_id,route_short_name,route_type\n101,{route},3\n"
            )
            (folder / "trips.txt").write_text("route_id,trip_headsign,direction_id\n101,City,0\n")
            (folder / "stops.txt").write_text("stop_id,stop_name,stop_lat,stop_lon\n" + stops)

        with tempfile.TemporaryDirectory() as folder, patch.dict(
            os.environ, BUS_BACKEND="duckdb", BUS_DUCKDB_PATH=str(Path(folder) / "test.duckdb")
        ), patch("bus_checker.reference.download_and_extract_gtfs", side_effect=write_feed):
            load_gtfs()
            stamp = read_frame("SELECT refreshed_at FROM bus_reference_refresh").iloc[0, 0]
            route = "B"
            for stops, error in [
                ("", "Empty"), (valid_stop * 2, "Duplicate"), (",City,-36.8,174.7\n", "Missing")
            ]:
                with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                    load_gtfs()
                self.assertEqual(read_frame("SELECT stop_id FROM gtfs_stops").stop_id.tolist(), ["001"])
                self.assertEqual(read_frame("SELECT route_short_name FROM gtfs_routes").iloc[0, 0], "A")
                self.assertEqual(read_frame("SELECT refreshed_at FROM bus_reference_refresh").iloc[0, 0], stamp)
            stops = valid_stop
            load_gtfs()
            self.assertEqual(read_frame("SELECT route_short_name FROM gtfs_routes").iloc[0, 0], "B")

    def test_partial_download_removes_temporary_file(self):
        created_files = []
        original_temporary_file = tempfile.NamedTemporaryFile

        def track_temporary_file(*args, **kwargs):
            temporary_file = original_temporary_file(*args, **kwargs)
            created_files.append(Path(temporary_file.name))
            return temporary_file

        def broken_stream(**kwargs):
            yield b"partial zip"
            raise OSError("connection interrupted")

        response = MagicMock()
        response.__enter__.return_value = response
        response.iter_content.side_effect = broken_stream
        with tempfile.TemporaryDirectory() as destination:
            with patch("bus_checker.reference.requests.get", return_value=response):
                with patch(
                    "bus_checker.reference.tempfile.NamedTemporaryFile",
                    side_effect=track_temporary_file,
                ):
                    with self.assertLogs("bus_checker.reference", level="ERROR"):
                        with self.assertRaises(OSError):
                            download_and_extract_gtfs(Path(destination))
        self.assertEqual(len(created_files), 1)
        self.assertFalse(created_files[0].exists())
        response.__exit__.assert_called_once()
