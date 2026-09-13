import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src.dedupe import job_id, normalize_url, empty_state, save_state, load_state


class DedupeTests(unittest.TestCase):
    def test_stability(self):
        self.assertEqual(job_id(" Acme ", "Product  Manager", "NY", "https://EXAMPLE.com/job/?utm_source=a&b=2&a=1#top"),
                         job_id("acme", "product manager", "ny", "https://example.com/job?a=1&b=2"))
        self.assertNotEqual(job_id("a", "b", "c", "https://example.com/A"),
                            job_id("a", "b", "c", "https://example.com/a"))
        self.assertNotEqual(job_id("a", "b", "c", "https://example.com/?id=1"),
                            job_id("a", "b", "c", "https://example.com/?id=2"))
        self.assertNotEqual(job_id("a", "b", "c", "https://example.com"),
                            job_id("a", "b", "d", "https://example.com"))

    def test_url_validation(self):
        for url in ("javascript:alert(1)", "/relative", "https://user@example.com"):
            with self.assertRaises(ValueError):
                normalize_url(url)

    def test_roundtrip_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            self.assertEqual(load_state(path), empty_state())
            save_state(path, empty_state())
            self.assertEqual(load_state(path), empty_state())
            path.write_text('{"version": 9}')
            with self.assertRaises(ValueError):
                load_state(path)
            path.write_text("broken")
            with self.assertRaises(json.JSONDecodeError):
                load_state(path)

    def test_failed_atomic_write_preserves_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            save_state(path, empty_state())
            with patch("src.dedupe.os.replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    save_state(path, {**empty_state(), "source": {"etag": "new"}})
            self.assertEqual(load_state(path), empty_state())
