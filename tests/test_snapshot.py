import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb

from bus_checker.snapshot import publish_snapshot


class DashboardSnapshotTests(unittest.TestCase):
    def test_failed_copy_preserves_last_publication_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "bus.duckdb"
            target = Path(folder) / "published" / source.name
            with patch.dict(os.environ, BUS_BACKEND="duckdb", BUS_DUCKDB_PATH=str(source),
                            BUS_SNAPSHOT_DIR=str(target.parent)):
                with duckdb.connect(str(source)) as writer:
                    writer.execute("CREATE TABLE samples AS SELECT 1 AS n")
                    writer.execute("CREATE VIEW total AS SELECT sum(n) FROM samples")
                publish_snapshot()
                with duckdb.connect(str(target), read_only=True) as reader:
                    with duckdb.connect(str(source)) as writer:
                        writer.execute("INSERT INTO samples VALUES (2)")
                    self.assertEqual(reader.execute("SELECT * FROM total").fetchone(), (1,))
                with patch("bus_checker.snapshot.shutil.copyfileobj", side_effect=OSError):
                    with self.assertRaises(OSError):
                        publish_snapshot()
                with duckdb.connect(str(target), read_only=True) as reader:
                    self.assertEqual(reader.execute("SELECT * FROM total").fetchone(), (1,))
                self.assertEqual(list(target.parent.iterdir()), [target])
                publish_snapshot()
                with duckdb.connect(str(target), read_only=True) as reader:
                    self.assertEqual(reader.execute("SELECT * FROM total").fetchone(), (3,))
