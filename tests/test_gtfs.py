import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from load_gtfs import download_and_extract_gtfs


class GtfsDownloadTests(unittest.TestCase):
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
            with patch("load_gtfs.requests.get", return_value=response):
                with patch(
                    "load_gtfs.tempfile.NamedTemporaryFile",
                    side_effect=track_temporary_file,
                ):
                    with self.assertLogs("load_gtfs", level="ERROR"):
                        with self.assertRaises(OSError):
                            download_and_extract_gtfs(Path(destination))
        self.assertEqual(len(created_files), 1)
        self.assertFalse(created_files[0].exists())
        response.__exit__.assert_called_once()
