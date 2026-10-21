import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from src.main import run
from src.dedupe import load_state
from src.http import FetchResult
from test_jobright import HEADER, ROW

NOW = 1792431600


class PipelineTests(unittest.TestCase):
    def _stub_new_sources(self, fetch_simplify, fetch_fyrf):
        fetch_simplify.return_value = FetchResult(None, None)
        fetch_fyrf.return_value = FetchResult(None, None)

    @patch("src.main.fetch_entry_level")
    @patch("src.main.fetch_listings")
    @patch("src.main.fetch_readme")
    def test_first_repeat_and_unchanged(self, fetch, fetch_simplify, fetch_fyrf):
        self._stub_new_sources(fetch_simplify, fetch_fyrf)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            rejected = ROW.replace("Associate Product Manager", "Senior Product Manager")
            fetch.return_value = FetchResult(HEADER + ROW + ROW + rejected, '"v1"')
            with redirect_stdout(io.StringIO()) as output:
                run(path, now_ts=NOW)
            self.assertEqual(output.getvalue().count("[NEW]"), 1)
            self.assertIn("Rejected 1", output.getvalue())
            self.assertIn("Already seen 1", output.getvalue())
            self.assertEqual(len(load_state(path)["jobs"]), 1)
            with redirect_stdout(io.StringIO()) as output:
                run(path, force=True, now_ts=NOW)
            self.assertNotIn("[NEW]", output.getvalue())
            self.assertEqual(fetch.call_args.args[0], None)
            before = path.read_bytes()
            fetch.return_value = FetchResult(None, '"v1"')
            with patch("src.main.parse_readme") as parse, redirect_stdout(io.StringIO()):
                run(path, now_ts=NOW)
                parse.assert_not_called()
            self.assertEqual(fetch.call_args.args[0], '"v1"')
            self.assertEqual(before, path.read_bytes())

    @patch("src.main.fetch_entry_level")
    @patch("src.main.fetch_listings")
    @patch("src.main.fetch_readme")
    def test_parse_failure_does_not_save_etag(self, fetch, fetch_simplify, fetch_fyrf):
        self._stub_new_sources(fetch_simplify, fetch_fyrf)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            fetch.return_value = FetchResult("invalid", "bad")
            with self.assertRaises(ValueError):
                run(path, now_ts=NOW)
            self.assertFalse(path.exists())

    @patch("src.main.fetch_entry_level")
    @patch("src.main.fetch_listings")
    @patch("src.main.fetch_readme")
    def test_policy_change_invalidates_etag(self, fetch, fetch_simplify, fetch_fyrf):
        self._stub_new_sources(fetch_simplify, fetch_fyrf)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            fetch.return_value = FetchResult(HEADER + ROW, "v1")
            with redirect_stdout(io.StringIO()):
                run(path, now_ts=NOW)
                with patch("src.main.policy_fingerprint", return_value="new-policy"):
                    run(path, now_ts=NOW)
            self.assertEqual(fetch.call_args.args[0], None)
