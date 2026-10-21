import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from src.http import FetchResult
from src.sources.simplify import fetch_listings, parse_listings

FIXTURE = Path(__file__).parent / "fixtures" / "simplify_listings.json"
NOW = 1792431600  # 2026-10-19 17:40 UTC


class SimplifyParserTests(unittest.TestCase):
    def setUp(self):
        self.payload = FIXTURE.read_text(encoding="utf-8")

    def test_keeps_fresh_us_pm_titles_across_categories(self):
        jobs = parse_listings(self.payload, now=NOW)
        titles = {(job.company, job.title) for job in jobs}
        self.assertEqual(titles, {
            ("Figma", "Associate Product Manager"),
            ("LSEG", "Senior Associate Product Manager - Enterprise AI"),
        })
        by_company = {job.company: job for job in jobs}
        self.assertEqual(by_company["Figma"].source, "simplify")
        self.assertEqual(by_company["Figma"].ats, "Greenhouse")
        self.assertTrue(by_company["Figma"].canonical_apply_url.startswith(
            "https://boards.greenhouse.io/figma/jobs/6180116004"))
        self.assertNotIn("utm_", by_company["Figma"].canonical_apply_url)
        self.assertFalse(by_company["LSEG"].canonical_apply_url.endswith("/apply"))
        self.assertEqual(by_company["LSEG"].location, "NYC")

    def test_drops_inactive_invisible_old_non_us_and_senior_pm(self):
        jobs = parse_listings(self.payload, now=NOW)
        companies = {job.company for job in jobs}
        self.assertNotIn("Hidden Co", companies)
        self.assertNotIn("Ghost Co", companies)
        self.assertNotIn("Old Co", companies)
        self.assertNotIn("Wise", companies)
        self.assertNotIn("BigCo", companies)
        self.assertNotIn("Citizens", companies)

    def test_fail_closed_on_object_payload(self):
        with self.assertRaises(ValueError):
            parse_listings('{"jobs": []}', now=NOW)

    def test_fail_closed_on_invalid_json(self):
        with self.assertRaises(ValueError):
            parse_listings("not-json", now=NOW)


class SimplifyFetchTests(unittest.TestCase):
    @patch("src.http.urlopen")
    def test_sends_etag_and_if_modified_since(self, open_url):
        response = MagicMock()
        response.read.return_value = b"[]"
        response.headers = {"ETag": '"abc"', "Last-Modified": "Mon, 19 Oct 2026 00:00:00 GMT"}
        open_url.return_value.__enter__.return_value = response
        result = fetch_listings('"old"', "Sun, 18 Oct 2026 00:00:00 GMT")
        self.assertEqual(result.text, "[]")
        self.assertEqual(result.etag, '"abc"')
        request = open_url.call_args.args[0]
        self.assertEqual(request.get_header("If-none-match"), '"old"')
        self.assertEqual(request.get_header("If-modified-since"), "Sun, 18 Oct 2026 00:00:00 GMT")
        self.assertEqual(open_url.call_args.kwargs["timeout"], 90)

    @patch("src.http.urlopen")
    def test_not_modified(self, open_url):
        open_url.side_effect = HTTPError("url", 304, "unchanged", {}, None)
        result = fetch_listings('"old"')
        self.assertIsInstance(result, FetchResult)
        self.assertIsNone(result.text)
        self.assertEqual(result.etag, '"old"')
