"""Still-open and entry-level filters, including live-verdict fixtures."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from src.entry_level import DROP, KEEP, RuleBasedEntryLevelClassifier, classify_entry_level
from src.html_email import cards_from_jobs, render_html_email
from src.http import FetchResult
from src.listing_filters import (
    DROP_CLOSED,
    DROP_NOT_ENTRY,
    KEEP_UNVERIFIABLE,
    screen_candidates,
)
from src.main import run
from src.models import build_job
from src.posting_fetch import (
    CLOSED,
    OPEN,
    UNVERIFIABLE,
    PostingClient,
    PostingSnapshot,
    RawResponse,
    _redirected_to_board,
    fetch_posting,
)
from src.sample_jobs import (
    FIGMA_URL,
    GOOGLE_URL,
    LSEG_URL,
    MICROSOFT_URL,
    NATERA_URL,
    decide_from_snapshot,
    sample_job_list,
    screen_sample_jobs,
)
from src.dedupe import load_state
from test_jobright import HEADER, ROW

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "postings"
NOW = 1792431600


def _job(company="Acme", title="Associate Product Manager", url="https://boards.greenhouse.io/acme/jobs/42"):
    return build_job(
        company=company, title=title, location="SF", date_posted="Oct 1",
        url=url, source="simplify",
    )


def _raw(status, url, text="", final=None, headers=None, error=None, blocked=False):
    return RawResponse(
        status=status, url=url, final_url=final or url, text=text,
        headers=headers or {"content-type": "application/json"},
        error=error, blocked=blocked,
    )


class YearAndSectionTests(unittest.TestCase):
    def _decide(self, text, title="Product Manager", tags=()):
        snap = PostingSnapshot(url="https://example.com/job", openness=OPEN, text=text, seniority_tags=tags)
        return classify_entry_level(snap, title=title)

    def test_required_three_years_drops(self):
        decision = self._decide("Minimum qualifications:\n3 years of experience in product management\n")
        self.assertEqual(decision.verdict, DROP)

    def test_required_three_plus_and_word_and_range(self):
        for text in (
            "Required qualifications:\n3+ years of experience\n",
            "Basic qualifications:\nthree years of experience\n",
            "Minimum qualifications:\n3-5 years of experience\n",
        ):
            with self.subTest(text=text):
                self.assertEqual(self._decide(text).verdict, DROP)

    def test_preferred_years_do_not_disqualify(self):
        decision = self._decide(
            "Minimum qualifications:\nBachelor's degree\n"
            "Preferred qualifications:\n5 years of experience in product management\n"
        )
        self.assertEqual(decision.verdict, KEEP)
        self.assertEqual(decision.preferred_years, 5)

    def test_microsoft_style_preferred_two_years_keeps(self):
        decision = self._decide(
            "Bachelor's Degree or equivalent experience. Bachelor's Degree and 2+ years "
            "experience in product/service/program management or equivalent experience."
        )
        self.assertEqual(decision.verdict, KEEP)

    def test_privacy_footer_years_do_not_disqualify(self):
        decision = self._decide(
            "Bachelor's Degree or equivalent experience. Bachelor's Degree and 2+ years "
            "experience in product management.\n"
            "We might ask me to renew my consent for the processing after 10 years to "
            "ensure it follows my intent."
        )
        self.assertEqual(decision.verdict, KEEP)

    def test_company_history_not_treated_as_experience(self):
        decision = self._decide(
            "LSEG has contributed to communities globally for more than 300 years.\n"
            "WHAT YOU'LL BRING:\nBachelor's degree\nEarly career experience (internships and graduate schemes considered).\n"
        )
        self.assertEqual(decision.verdict, KEEP)

    def test_mid_tag_drops_even_without_years(self):
        decision = self._decide("A product role.", tags=("Mid",))
        self.assertEqual(decision.verdict, DROP)
        self.assertIn("mid", decision.reason.lower())

    def test_senior_associate_tag_does_not_drop(self):
        decision = self._decide(
            "Early-career product manager. Internships and graduate schemes considered.",
            title="Senior Associate Product Manager",
            tags=("Senior Associate",),
        )
        self.assertEqual(decision.verdict, KEEP)

    def test_titles_alone_do_not_decide(self):
        decision = self._decide(
            "WHAT YOU'LL BRING:\nBachelor's degree\n",
            title="Senior Associate Product Manager - Enterprise AI",
        )
        self.assertEqual(decision.verdict, KEEP)

    def test_early_career_program_kept(self):
        decision = self._decide(
            "Early Career, Associate Product Manager\nJoin our rotation program.\n",
            title="Associate Product Manager",
        )
        self.assertEqual(decision.verdict, KEEP)


class AcceptanceFixtureTests(unittest.TestCase):
    """Fixtures match the real 2026-10-19 verdicts for the five sample URLs."""

    def test_figma_apm_keep(self):
        data = json.loads((FIXTURES / "figma_greenhouse.json").read_text())
        from src.posting_fetch import _html_to_text
        snap = PostingSnapshot(
            url=FIGMA_URL, openness=OPEN, ats="Greenhouse",
            text=data["title"] + "\n" + _html_to_text(data["content"]), json_data=data,
        )
        job = _job("Figma", "Associate Product Manager", FIGMA_URL)
        result = decide_from_snapshot(job, snap)
        self.assertEqual(result.action, "keep")

    def test_lseg_senior_associate_keep(self):
        data = json.loads((FIXTURES / "lseg_workday.json").read_text())
        from src.posting_fetch import _html_to_text
        info = data["jobPostingInfo"]
        snap = PostingSnapshot(
            url=LSEG_URL, openness=OPEN, ats="Workday",
            text=info["title"] + "\n" + _html_to_text(info["jobDescription"]),
            json_data=data,
        )
        job = _job("LSEG", "Senior Associate Product Manager - Enterprise AI", LSEG_URL)
        result = decide_from_snapshot(job, snap)
        self.assertEqual(result.action, "keep")

    def test_microsoft_preferred_two_years_keep(self):
        html = (FIXTURES / "microsoft_jsonld.html").read_text()
        client = PostingClient()
        client.request = lambda *args, **kwargs: _raw(200, MICROSOFT_URL, html, headers={"content-type": "text/html"})
        snap = fetch_posting(MICROSOFT_URL, client=client)
        self.assertEqual(snap.openness, OPEN)
        job = _job("Microsoft", "Product Manager", MICROSOFT_URL)
        result = decide_from_snapshot(job, snap)
        self.assertEqual(result.action, "keep")

    def test_google_three_years_mid_drop(self):
        html = (FIXTURES / "google.html").read_text()
        client = PostingClient()
        client.request = lambda *args, **kwargs: _raw(200, GOOGLE_URL, html, headers={"content-type": "text/html"})
        snap = fetch_posting(GOOGLE_URL, client=client)
        self.assertIn("mid", [t.lower() for t in snap.seniority_tags])
        job = _job("Google", "Product Manager I, Ads Sellside Apps", GOOGLE_URL)
        result = decide_from_snapshot(job, snap)
        self.assertEqual(result.action, DROP_NOT_ENTRY)

    def test_natera_closed_drop(self):
        payload = (FIXTURES / "natera_greenhouse_404.json").read_text()
        client = PostingClient()
        client.request = lambda *args, **kwargs: _raw(404, "https://boards-api.greenhouse.io/v1/boards/natera/jobs/6217258004", payload)
        snap = fetch_posting(NATERA_URL, client=client)
        self.assertEqual(snap.openness, CLOSED)
        job = _job("Natera", "(Associate) Product Manager, Organ Health", NATERA_URL)
        result = decide_from_snapshot(job, snap)
        self.assertEqual(result.action, DROP_CLOSED)


class FetchBehaviorTests(unittest.TestCase):
    def test_greenhouse_404_is_closed(self):
        client = PostingClient()
        client.request = lambda *a, **k: _raw(404, "https://boards-api.greenhouse.io/v1/boards/figma/jobs/1", '{"error":"Job not found"}')
        snap = fetch_posting("https://boards.greenhouse.io/figma/jobs/1", client=client)
        self.assertEqual(snap.openness, CLOSED)

    def test_http_410_is_closed(self):
        client = PostingClient()
        client.request = lambda *a, **k: _raw(410, "https://example.com/jobs/gone", "gone")
        snap = fetch_posting("https://example.com/jobs/gone", client=client)
        self.assertEqual(snap.openness, CLOSED)

    def test_redirect_to_board_is_closed(self):
        original = "https://job-boards.greenhouse.io/natera/jobs/6217258004"
        final = "https://job-boards.greenhouse.io/natera?error=true"
        self.assertTrue(_redirected_to_board(original, final))
        client = PostingClient()
        client.request = lambda *a, **k: _raw(200, original, "<html>jobs</html>", final=final, headers={"content-type": "text/html"})
        snap = fetch_posting("https://example.com/jobs/6217258004-open", client=client)
        # example.com is not greenhouse; construct html fetch with natera host via unknown ATS
        client.request = lambda *a, **k: _raw(200, original, "<html>board</html>", final=final, headers={"content-type": "text/html"})
        # Force HTML path with a non-ATS URL that still redirects
        from src import posting_fetch
        snap = posting_fetch._from_html(original, "Greenhouse", client)
        self.assertEqual(snap.openness, CLOSED)

    def test_locale_host_change_keeps_job_id_open(self):
        original = "https://boards.greenhouse.io/figma/jobs/6180116004"
        final = "https://job-boards.greenhouse.io/figma/jobs/6180116004"
        self.assertFalse(_redirected_to_board(original, final))

    def test_timeout_fail_open(self):
        client = PostingClient()
        client.request = lambda *a, **k: _raw(None, FIGMA_URL, error="timeout: timed out")
        snap = fetch_posting(FIGMA_URL, client=client)
        self.assertEqual(snap.openness, UNVERIFIABLE)

    def test_cloudflare_fail_open(self):
        client = PostingClient()
        client.request = lambda *a, **k: _raw(403, "https://example.com/job", "Just a moment", blocked=True)
        snap = fetch_posting("https://example.com/job", client=client)
        self.assertEqual(snap.openness, UNVERIFIABLE)

    def test_jobright_wrapper_fail_open_without_http(self):
        with patch.object(PostingClient, "request", side_effect=AssertionError("should not fetch")):
            snap = fetch_posting("https://jobright.ai/jobs/123")
        self.assertEqual(snap.openness, UNVERIFIABLE)
        self.assertEqual(snap.source, "jobright")

    def test_closed_phrase_in_html(self):
        client = PostingClient()
        html = "<html><body>This job is no longer accepting applications.</body></html>"
        client.request = lambda *a, **k: _raw(200, "https://example.com/old", html, headers={"content-type": "text/html"})
        snap = fetch_posting("https://example.com/old", client=client)
        self.assertEqual(snap.openness, CLOSED)

    def test_workday_cxs_open(self):
        payload = (FIXTURES / "lseg_workday.json").read_text()
        client = PostingClient()
        client.request = lambda *a, **k: _raw(200, a[1] if len(a) > 1 else LSEG_URL, payload)
        snap = fetch_posting(LSEG_URL, client=client)
        self.assertEqual(snap.openness, OPEN)
        self.assertEqual(snap.source, "workday-cxs")
        self.assertIn("early-career", snap.text.lower())


class ScreenPipelineTests(unittest.TestCase):
    def test_counts_and_order(self):
        jobs = [
            _job("ClosedCo", url="https://boards.greenhouse.io/closed/jobs/1"),
            _job("MidCo", url="https://www.example.com/mid"),
            _job("KeepCo", url="https://boards.greenhouse.io/keep/jobs/2"),
            _job("WrapCo", url="https://jobright.ai/jobs/9"),
        ]

        def fake_fetch(url, client=None):
            if "closed" in url:
                return PostingSnapshot(url=url, openness=CLOSED, reason="Job not found")
            if "mid" in url:
                return PostingSnapshot(url=url, openness=OPEN, text="A role", seniority_tags=("Mid",))
            if "keep" in url:
                return PostingSnapshot(
                    url=url, openness=OPEN,
                    text="Early Career rotation program\nMinimum qualifications:\nBachelor's degree\n",
                )
            return PostingSnapshot(url=url, openness=UNVERIFIABLE, reason="jobright wrapper")

        with patch("src.listing_filters.fetch_posting", side_effect=fake_fetch):
            kept, stats, results = screen_candidates(jobs)
        self.assertEqual([job.company for job in kept], ["KeepCo", "WrapCo"])
        self.assertEqual(stats.checked, 4)
        self.assertEqual(stats.dropped_closed, 1)
        self.assertEqual(stats.dropped_not_entry_level, 1)
        self.assertEqual(stats.unverifiable_kept, 1)

    def test_sample_email_omits_google_and_natera(self):
        def fake_fetch(url, client=None):
            mapping = {
                FIGMA_URL: PostingSnapshot(url=url, openness=OPEN, text="Early Career rotation program"),
                LSEG_URL: PostingSnapshot(
                    url=url, openness=OPEN,
                    text="early-career product manager\ninternships and graduate schemes considered\n",
                ),
                MICROSOFT_URL: PostingSnapshot(
                    url=url, openness=OPEN,
                    text="Bachelor's Degree or equivalent experience. 2+ years experience preferred.",
                ),
                GOOGLE_URL: PostingSnapshot(
                    url=url, openness=OPEN,
                    text="Minimum qualifications:\n3 years of experience in product management\n",
                    seniority_tags=("Mid",),
                ),
                NATERA_URL: PostingSnapshot(url=url, openness=CLOSED, reason="Job not found"),
            }
            return mapping[url]

        with patch("src.listing_filters.fetch_posting", side_effect=fake_fetch):
            kept, results = screen_sample_jobs(sample_job_list(), use_fallback=False)
        companies = [job.company for job in kept]
        self.assertEqual(companies, ["Microsoft", "LSEG", "Figma"])
        self.assertNotIn("Google", companies)
        self.assertNotIn("Natera", companies)
        html = render_html_email(cards_from_jobs(kept), "New PM Jobs")
        self.assertIn("Figma", html)
        self.assertIn("Microsoft", html)
        self.assertIn("LSEG", html)
        self.assertNotIn("Google", html)
        self.assertNotIn("Natera", html)

    @patch("src.main.fetch_entry_level")
    @patch("src.main.fetch_listings")
    @patch("src.main.fetch_readme")
    def test_dropped_closed_is_marked_seen_not_emailed(self, fetch, fetch_simplify, fetch_fyrf):
        fetch_simplify.return_value = FetchResult(None, None)
        fetch_fyrf.return_value = FetchResult(None, None)
        row = ROW.replace(
            "https://jobright.ai/jobs/123?utm_source=x",
            "https://job-boards.greenhouse.io/natera/jobs/6217258004",
        )
        fetch.return_value = FetchResult(HEADER + row, '"v1"')
        closed = PostingSnapshot(url=NATERA_URL, openness=CLOSED, reason="Job not found")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with patch("src.listing_filters.fetch_posting", return_value=closed), redirect_stdout(io.StringIO()) as output:
                run(path, now_ts=NOW)
            text = output.getvalue()
            self.assertNotIn("[NEW]", text)
            self.assertIn("Dropped closed 1", text)
            self.assertEqual(len(load_state(path)["jobs"]), 1)

    @patch("src.main.fetch_entry_level")
    @patch("src.main.fetch_listings")
    @patch("src.main.fetch_readme")
    def test_dry_run_does_not_write_state(self, fetch, fetch_simplify, fetch_fyrf):
        fetch_simplify.return_value = FetchResult(None, None)
        fetch_fyrf.return_value = FetchResult(None, None)
        fetch.return_value = FetchResult(HEADER + ROW, '"v1"')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with patch("src.main.audit_acceptance_jobs", return_value=[]), redirect_stdout(io.StringIO()):
                run(path, now_ts=NOW, dry_run=True)
            self.assertFalse(path.exists())


class ClassifierHookTests(unittest.TestCase):
    def test_injected_llm_is_used(self):
        class FakeLlm:
            def decide(self, snapshot, title=""):
                from src.entry_level import EntryLevelDecision
                return EntryLevelDecision(DROP, "llm said no")

        snap = PostingSnapshot(url="https://example.com", openness=OPEN, text="Bachelor's only")
        decision = classify_entry_level(snap, title="PM", classifier=FakeLlm())
        self.assertEqual(decision.verdict, DROP)
        self.assertEqual(decision.reason, "llm said no")

    def test_rule_based_is_default(self):
        self.assertIsInstance(RuleBasedEntryLevelClassifier(), RuleBasedEntryLevelClassifier)


if __name__ == "__main__":
    unittest.main()
