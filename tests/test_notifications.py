import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from src.dedupe import empty_state, load_state, save_state
from src.main import run
from src.notifications import (TwilioClient, SmsError, load_dotenv, enqueue,
                               deliver, digest_body)
from src.sources.jobright import FetchResult, parse_readme
from dataclasses import asdict
from test_jobright import HEADER, ROW

SID = "SM" + "a" * 32


class SmsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        self.state = empty_state()
        self.client = MagicMock()
        self.client.send.return_value = {"sid": SID, "status": "queued"}
        self.client.status.return_value = {"sid": SID, "status": "delivered"}

    def test_one_time_test_and_receipt(self):
        enqueue(self.state, [], test=True)
        deliver(self.state, self.path, self.client)
        self.assertEqual(load_state(self.path)["sms"]["test-v1"]["status"], "accepted")
        enqueue(self.state, [], test=True)
        deliver(self.state, self.path, self.client)
        self.assertEqual(self.client.send.call_count, 1)
        self.assertEqual(load_state(self.path)["sms"]["test-v1"]["status"], "delivered")

    def test_429_retries_on_next_run(self):
        enqueue(self.state, [], test=True)
        self.client.send.side_effect = SmsError("rate limited", retryable=True)
        with self.assertRaises(SmsError):
            deliver(self.state, self.path, self.client)
        self.assertEqual(load_state(self.path)["sms"]["test-v1"]["status"], "pending")
        self.client.send.side_effect = None
        deliver(self.state, self.path, self.client)
        self.assertEqual(self.client.send.call_count, 2)

    def test_timeout_not_blindly_retried(self):
        enqueue(self.state, [], test=True)
        self.client.send.side_effect = SmsError("timeout", uncertain=True)
        for _ in range(2):
            with self.assertRaises(SmsError):
                deliver(self.state, self.path, self.client)
        self.assertEqual(self.client.send.call_count, 1)
        self.assertEqual(load_state(self.path)["sms"]["test-v1"]["status"], "uncertain")

    def test_interrupted_send_requires_reconciliation(self):
        enqueue(self.state, [], test=True)
        self.state["sms"]["test-v1"]["status"] = "sending"
        with self.assertRaises(SmsError):
            deliver(self.state, self.path, self.client)
        self.client.send.assert_not_called()

    def test_failed_receipts_have_bounded_retries(self):
        enqueue(self.state, [], test=True)
        self.client.status.return_value = {"status": "undelivered", "error_code": 30003}
        for _ in range(3):
            deliver(self.state, self.path, self.client)
        with self.assertRaises(SmsError):
            deliver(self.state, self.path, self.client)
        self.assertEqual(self.client.send.call_count, 3)
        self.assertEqual(load_state(self.path)["sms"]["test-v1"]["status"], "blocked")

    def test_digest_bounded_and_only_one_send(self):
        job = asdict(parse_readme(HEADER + ROW)[0])
        body = digest_body([job] * 120)
        self.assertLessEqual(len(body), 900)
        self.assertIn("120 new", body)
        self.assertIn("more in run logs", body)
        enqueue(self.state, [job], test=True)
        deliver(self.state, self.path, self.client)
        self.assertEqual(self.client.send.call_count, 1)
        self.assertEqual(len(self.state["sms"]), 2)

    @patch("src.main.fetch_readme")
    def test_existing_jobs_excluded_and_new_jobs_queued(self, fetch):
        fetch.return_value = FetchResult(HEADER + ROW, "v1")
        with redirect_stdout(io.StringIO()):
            run(self.path)
            run(self.path, client=self.client)
        self.client.send.assert_not_called()
        fetch.return_value = FetchResult(HEADER + ROW.replace("/123", "/456"), "v2")
        with redirect_stdout(io.StringIO()):
            run(self.path, client=self.client)
        self.client.send.assert_called_once()

    @patch("src.main.fetch_readme")
    def test_unchanged_source_still_processes_queue(self, fetch):
        enqueue(self.state, [], test=True)
        save_state(self.path, self.state)
        fetch.return_value = FetchResult(None, "v1")
        with redirect_stdout(io.StringIO()):
            run(self.path, client=self.client)
        self.client.send.assert_called_once()

    def test_invalid_outbox_fails_closed(self):
        self.state["sms"] = {"bad": {"status": "anything"}}
        save_state(self.path, self.state)
        with self.assertRaises(ValueError):
            load_state(self.path)

    @patch.dict(os.environ, {"AUTH_TOKEN": "process-secret"}, clear=True)
    def test_dotenv_is_literal_and_preserves_environment(self):
        path = self.path.with_name(".env")
        path.write_text('# comment\nACCOUNT_SID="ACexample"\nAUTH_TOKEN=file-secret\nX=$(do-not-execute)\n')
        load_dotenv(path)
        self.assertEqual(os.environ["AUTH_TOKEN"], "process-secret")
        self.assertEqual(os.environ["ACCOUNT_SID"], "ACexample")
        self.assertEqual(os.environ["X"], "$(do-not-execute)")

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_credentials_fail_before_network(self):
        with self.assertRaisesRegex(ValueError, "Missing SMS settings"):
            TwilioClient.from_environment()


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TwilioClient("AC" + "a" * 32, "secret", "+12025550101", "+12025550102")

    @patch("src.notifications.urlopen")
    def test_request_and_safe_errors(self, open_url):
        open_url.return_value.__enter__.return_value.read.return_value = json.dumps({"sid": SID, "status": "queued"}).encode()
        self.client.send("Hello")
        request = open_url.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertIn(b"Body=Hello", request.data)
        self.assertEqual(open_url.call_args.kwargs["timeout"], 30)
        open_url.side_effect = HTTPError("url", 400, "bad", {}, io.BytesIO(b'{"code":21211,"message":"private phone"}'))
        with self.assertRaises(SmsError) as error:
            self.client.send("Hello")
        self.assertIn("21211", str(error.exception))
        self.assertNotIn("private phone", str(error.exception))
        self.assertFalse(error.exception.uncertain)

    @patch("src.notifications.urlopen", side_effect=URLError("private details"))
    def test_network_error_is_uncertain_and_sanitized(self, open_url):
        with self.assertRaises(SmsError) as error:
            self.client.send("Hello")
        self.assertTrue(error.exception.uncertain)
        self.assertNotIn("private details", str(error.exception))
        self.assertEqual(open_url.call_count, 1)
