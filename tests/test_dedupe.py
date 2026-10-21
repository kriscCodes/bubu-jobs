import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.dedupe import (
    apply_url_key,
    build_seen_index,
    company_title_key,
    dedupe_jobs,
    empty_state,
    is_seen_job,
    job_id,
    load_state,
    normalize_apply_url,
    normalize_url,
    save_state,
)
from src.main import classify_jobs
from src.models import build_job


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


class ApplyUrlNormalizationTests(unittest.TestCase):
    def test_strips_tracking_apply_suffix_and_lowercases_host(self):
        self.assertEqual(
            normalize_apply_url(
                "https://JOBS.lever.co/acme/abc/apply?utm_source=x&ref=board&id=1#frag"
            ),
            "https://jobs.lever.co/acme/abc?id=1",
        )

    def test_company_title_key_ignores_case_and_space(self):
        self.assertEqual(
            company_title_key(" Figma ", "Associate  Product Manager"),
            company_title_key("figma", "associate product manager"),
        )


class CrossSourceDedupeTests(unittest.TestCase):
    def test_dedupes_on_normalized_url_then_company_title(self):
        simplify = build_job(
            company="Figma", title="Associate Product Manager", location="SF",
            date_posted="Oct 7", url="https://boards.greenhouse.io/figma/jobs/1/apply?utm_source=s",
            source="simplify", date_posted_ts=1792000000,
        )
        fyrf = build_job(
            company="Figma", title="Associate Product Manager", location="San Francisco",
            date_posted="Oct 7", url="https://boards.greenhouse.io/figma/jobs/1?ref=fyrf",
            source="findyourrolefirst", date_posted_ts=1792000000,
        )
        jobright = build_job(
            company="Figma", title="Associate Product Manager", location="Remote",
            date_posted="Oct 7", url="https://jobright.ai/jobs/info/abc",
            source="jobright", canonical=False, date_posted_ts=None,
        )
        unique = dedupe_jobs([simplify, fyrf, jobright])
        self.assertEqual([job.source for job in unique], ["simplify"])

    def test_seen_index_matches_url_or_company_title(self):
        stored = build_job(
            company="Acme", title="Product Manager", location="NY",
            date_posted="Sep 11", url="https://jobright.ai/jobs/123",
            source="jobright", canonical=False,
        )
        index = build_seen_index({stored.job_id: {
            "company": stored.company, "title": stored.title,
            "source_url": stored.source_url, "canonical_apply_url": None,
            "job_id": stored.job_id,
        }})
        same_title_new_url = build_job(
            company="Acme", title="Product Manager", location="New York",
            date_posted="Oct 1", url="https://boards.greenhouse.io/acme/jobs/99",
            source="simplify",
        )
        self.assertTrue(is_seen_job(same_title_new_url, index))
        other = build_job(
            company="Other", title="Product Analyst", location="SF",
            date_posted="Oct 1", url="https://boards.greenhouse.io/other/jobs/1",
            source="simplify",
        )
        self.assertFalse(is_seen_job(other, index))
        self.assertEqual(apply_url_key("https://Example.com/job/apply?ref=1"),
                         "https://example.com/job")


class FirstRunSuppressionTests(unittest.TestCase):
    def test_seeds_old_new_source_jobs_and_alerts_fresh_ones(self):
        now = 1792431600
        old = build_job(
            company="OldCo", title="Associate Product Manager", location="SF",
            date_posted="Oct 6", url="https://boards.greenhouse.io/old/1",
            source="simplify", date_posted_ts=now - 6 * 86400,
        )
        fresh = build_job(
            company="NewCo", title="Associate Product Manager", location="NYC",
            date_posted="Oct 18", url="https://boards.greenhouse.io/new/1",
            source="simplify", date_posted_ts=now - 86400,
        )
        jobright = build_job(
            company="Acme", title="Associate Product Manager", location="NY",
            date_posted="Sep 11", url="https://jobright.ai/jobs/123",
            source="jobright", canonical=False,
        )
        state = empty_state()
        new, already_seen, seeded = classify_jobs(
            [old, fresh, jobright], state, now, first_run_sources={"simplify", "findyourrolefirst"}
        )
        self.assertEqual(seeded, 1)
        self.assertEqual(already_seen, 0)
        self.assertEqual({job.company for job in new}, {"NewCo", "Acme"})
        self.assertIn(old.job_id, state["jobs"])
        self.assertNotIn("OldCo", {job.company for job in new})

    def test_second_run_does_not_seed(self):
        now = 1792431600
        old = build_job(
            company="OldCo", title="Associate Product Manager", location="SF",
            date_posted="Oct 6", url="https://boards.greenhouse.io/old/1",
            source="simplify", date_posted_ts=now - 6 * 86400,
        )
        state = empty_state()
        state["sources"]["simplify"] = {"seeded": True}
        new, already_seen, seeded = classify_jobs([old], state, now, first_run_sources=set())
        self.assertEqual(seeded, 0)
        self.assertEqual(already_seen, 0)
        self.assertEqual([job.company for job in new], ["OldCo"])

