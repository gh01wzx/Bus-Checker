import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from bus_checker.ingestion import collect_burst, run_pipeline
from bus_checker.database import ROOT, connect, read_frame


def feed(timestamp=1783396800, delay=90, trip_id="trip-1"):
    return {
        "response": {
            "header": {"timestamp": timestamp},
            "entity": [
                {
                    "trip_update": {
                        "trip": {
                            "route_id": "101",
                            "trip_id": trip_id,
                            "direction_id": 0,
                        },
                        "delay": delay,
                        "stop_time_update": [
                            {
                                "stop_id": "001",
                                "stop_sequence": 1,
                                "arrival": {"delay": delay},
                            }
                        ],
                    }
                }
            ],
        }
    }


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "BUS_BACKEND": "duckdb",
                "BUS_DUCKDB_PATH": self.directory.name + "/test.duckdb",
            },
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()

    def count(self, table):
        return int(read_frame(f"SELECT count(*) AS n FROM {table}").iloc[0].n)

    def run_command(self, *arguments):
        return subprocess.run(
            [sys.executable, str(ROOT / "pipeline.py"), *arguments],
            cwd=self.directory.name,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cli_file_import_and_replay_are_repeatable(self):
        archive = Path(self.directory.name) / "feed.json"
        archive.write_text(json.dumps(feed()), encoding="utf-8")
        first = self.run_command("collect", "--file", str(archive))
        self.assertEqual(first.returncode, 0, first.stderr)
        result = json.loads(first.stdout)
        self.assertEqual(result["accepted_rows"], 2)
        replay = self.run_command("collect", "--replay", result["batch_id"])
        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertEqual(json.loads(replay.stdout)["status"], "duplicate")
        legacy = self.run_command(f"--file={archive}")
        self.assertEqual(legacy.returncode, 0, legacy.stderr)
        self.assertEqual(json.loads(legacy.stdout)["status"], "duplicate")
        self.assertEqual(self.count("bus_observations"), 2)

    def test_cli_rejects_unknown_batch_and_conflicting_sources(self):
        run_pipeline(feed())
        unknown = self.run_command("collect", "--replay", "missing")
        self.assertEqual(unknown.returncode, 2)
        self.assertIn("Unknown batch ID", unknown.stderr)
        conflicting = self.run_command("collect", "--burst", "--file", "feed.json")
        self.assertEqual(conflicting.returncode, 2)
        self.assertEqual(self.count("bus_ingestion_runs"), 1)

    def test_burst_reports_failure_after_remaining_attempts(self):
        with patch(
            "bus_checker.ingestion.run_pipeline",
            side_effect=[{}, RuntimeError("interrupted"), {}],
        ) as collect:
            with patch("bus_checker.ingestion.time.sleep") as sleep:
                with self.assertLogs("bus_checker.ingestion", level="ERROR"):
                    with self.assertRaisesRegex(SystemExit, "1/3"):
                        collect_burst(bursts=3, interval_seconds=1)
        self.assertEqual(collect.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_burst_succeeds_without_waiting_after_last_attempt(self):
        with patch("bus_checker.ingestion.run_pipeline") as collect:
            with patch("bus_checker.ingestion.time.sleep") as sleep:
                collect_burst(bursts=1)
        collect.assert_called_once_with()
        sleep.assert_not_called()

    def test_replay_does_not_duplicate_fact_or_legacy_tables(self):
        self.assertEqual(run_pipeline(feed())["accepted_rows"], 2)
        self.assertEqual(run_pipeline(feed())["status"], "duplicate")
        self.assertEqual(self.count("bus_observations"), 2)
        self.assertEqual(self.count("trip_punctuality"), 1)
        self.assertEqual(self.count("stop_punctuality"), 1)
        self.assertEqual(self.count("bus_ingestion_runs"), 2)

    def test_invalid_record_is_quarantined_without_losing_valid_trip(self):
        payload = feed()
        payload["response"]["entity"].append(
            {"trip_update": {"trip": {"trip_id": "broken"}, "delay": 9}}
        )
        result = run_pipeline(payload)
        self.assertEqual(
            (result["status"], result["accepted_rows"], result["rejected_rows"]),
            ("warning", 2, 1),
        )
        self.assertEqual(self.count("bus_quarantine"), 1)

    def test_reordered_entities_have_same_batch_identity(self):
        payload = feed()
        payload["response"]["entity"] += feed(trip_id="trip-2")["response"]["entity"]
        run_pipeline(payload)
        payload["response"]["entity"].reverse()
        self.assertEqual(run_pipeline(payload)["status"], "duplicate")
        self.assertEqual(self.count("bus_observations"), 4)

    def test_duplicates_inside_feed_are_counted_once(self):
        payload = feed()
        payload["response"]["entity"] *= 2
        result = run_pipeline(payload)
        self.assertEqual((result["accepted_rows"], result["duplicate_rows"]), (2, 2))

    def test_late_event_preserves_source_time_and_new_ingestion_time(self):
        run_pipeline(feed())
        run_pipeline(feed(timestamp=1700000000, trip_id="late"))
        rows = read_frame("SELECT * FROM bus_observations WHERE trip_id='late'")
        self.assertEqual(len(rows), 2)
        self.assertTrue((rows.loaded_at > rows.captured_at).all())

    def test_malformed_feed_records_failure(self):
        with self.assertRaises(ValueError):
            run_pipeline({"response": {}})
        self.assertEqual(
            read_frame("SELECT status FROM bus_ingestion_runs").iloc[0].status, "failed"
        )

    def test_failure_rolls_back_batch_and_legacy_writes(self):
        run_pipeline(feed())
        from bus_checker.database import Connection

        original = Connection.many

        def fail_on_stop(connection, sql, params=None):
            if "INSERT INTO stop_punctuality" in sql:
                raise RuntimeError("forced failure after trip insert")
            return original(connection, sql, params)

        with patch.object(Connection, "many", fail_on_stop):
            with self.assertRaises(RuntimeError):
                run_pipeline(feed(timestamp=1783396900))
        self.assertEqual(self.count("bus_raw_batches"), 1)
        self.assertEqual(self.count("bus_observations"), 2)
        self.assertEqual(self.count("trip_punctuality"), 1)
        self.assertEqual(
            read_frame("SELECT status FROM bus_ingestion_runs ORDER BY started_at DESC")
            .iloc[0]
            .status,
            "failed",
        )

    def test_missing_direction_allowed_and_bad_delay_not_silently_zero(self):
        payload = feed(delay="not-a-delay")
        del payload["response"]["entity"][0]["trip_update"]["trip"]["direction_id"]
        result = run_pipeline(payload)
        self.assertEqual(result["accepted_rows"], 0)
        self.assertEqual(result["rejected_rows"], 2)

    def test_history_import_is_repeatable_and_does_not_append_legacy(self):
        from bus_checker.reference import import_history

        run_pipeline(feed())
        count = self.count("trip_punctuality")
        import_history()
        self.assertEqual(self.count("bus_observations"), 2)
        with connect(write=True) as conn:
            conn.execute("DELETE FROM bus_observations")
            conn.execute("DELETE FROM bus_raw_batches")
        import_history()
        first = self.count("bus_observations")
        import_history()
        self.assertEqual(self.count("bus_observations"), first)
        self.assertEqual(self.count("trip_punctuality"), count)


if __name__ == "__main__":
    unittest.main()
