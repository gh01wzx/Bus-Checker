import os
import tempfile
import unittest
from unittest.mock import patch

from ingestion import run_pipeline
from warehouse import connect, read_frame


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
        from warehouse import Connection

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
        from import_history import import_history

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
