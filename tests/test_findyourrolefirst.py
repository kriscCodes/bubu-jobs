import json
import unittest
from pathlib import Path
from unittest.mock import patch

from src.sources.findyourrolefirst import parse_entry_level

FIXTURE = Path(__file__).parent / "fixtures" / "findyourrolefirst.json"
NOW = 1792431600  # 2026-10-19 17:40 UTC


class FindYourRoleFirstParserTests(unittest.TestCase):
    def setUp(self):
        self.payload = FIXTURE.read_text(encoding="utf-8")

    def test_uses_product_track_and_filters(self):
        jobs = parse_entry_level(self.payload, now=NOW)
        companies = {job.company: job for job in jobs}
        self.assertEqual(set(companies), {"BD", "Lumafield"})
        self.assertEqual(companies["BD"].source, "findyourrolefirst")
        self.assertEqual(companies["BD"].ats, "Workday")
        self.assertTrue(companies["Lumafield"].canonical_apply_url.endswith(
            "b3eb6e02-0b51-420c-b708-61ed81d93220"))
        self.assertNotIn("/apply", companies["Lumafield"].canonical_apply_url)

    def test_ignores_other_tracks_and_non_matching_titles(self):
        jobs = parse_entry_level(self.payload, now=NOW)
        titles = {job.title for job in jobs}
        self.assertNotIn("Product Owner I (Entry-Level)", titles)
        self.assertNotIn("Senior Product Manager", titles)
        companies = {job.company for job in jobs}
        self.assertNotIn("ShouldNotSee", companies)
        self.assertNotIn("Abroad Co", companies)

    def test_fail_closed_on_missing_product_track(self):
        payload = json.dumps({"tracks": {"data": {"jobs": []}}})
        with self.assertRaises(ValueError):
            parse_entry_level(payload, now=NOW)

    def test_fail_closed_on_jobs_not_list(self):
        payload = json.dumps({"tracks": {"product": {"jobs": {"title": "x"}}}})
        with self.assertRaises(ValueError):
            parse_entry_level(payload, now=NOW)


class FindYourRoleFirstFailSoftTests(unittest.TestCase):
    @patch("src.main.fetch_entry_level", side_effect=RuntimeError("boom"))
    @patch("src.main.fetch_listings")
    @patch("src.main.fetch_readme")
    def test_collect_continues_when_fyrf_errors(self, fetch_readme, fetch_listings, fetch_fyrf):
        from src.dedupe import empty_state
        from src.http import FetchResult
        from src.main import collect_jobs, policy_fingerprint
        from test_jobright import HEADER, ROW

        fetch_listings.return_value = FetchResult(None, None)
        fetch_readme.return_value = FetchResult(HEADER + ROW, '"v1"')
        state = empty_state()
        jobs, downloaded, new_sources = collect_jobs(state, True, policy_fingerprint(), NOW)
        self.assertTrue(downloaded)
        self.assertEqual(new_sources, set())
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "Acme")
