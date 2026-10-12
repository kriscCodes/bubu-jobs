"""Tests for HTML email generation."""
import unittest

from src.html_email import (
    JobCard,
    render_html_email,
    render_plain_text_email,
    create_job_cards_from_jobs,
    _escape,
)


class EscapeTests(unittest.TestCase):
    """Tests for HTML escaping."""
    
    def test_escape_special_chars(self):
        self.assertEqual(_escape("<script>"), "&lt;script&gt;")
        self.assertEqual(_escape("A & B"), "A &amp; B")
        self.assertEqual(_escape('"quoted"'), "&quot;quoted&quot;")
    
    def test_escape_normal_text(self):
        self.assertEqual(_escape("Normal text"), "Normal text")


class JobCardTests(unittest.TestCase):
    """Tests for JobCard dataclass."""
    
    def test_job_card_creation(self):
        card = JobCard(
            company="Test Corp",
            title="Product Manager",
            location="New York, NY",
            date="Oct 12",
            apply_url="https://example.com/apply",
            is_direct_link=True,
        )
        self.assertEqual(card.company, "Test Corp")
        self.assertTrue(card.is_direct_link)
    
    def test_job_card_default_note(self):
        card = JobCard(
            company="Test",
            title="PM",
            location="SF",
            date="Today",
            apply_url="https://test.com",
            is_direct_link=False,
        )
        self.assertEqual(card.source_note, "")


class RenderHtmlEmailTests(unittest.TestCase):
    """Tests for HTML email rendering."""
    
    def setUp(self):
        self.test_cards = [
            JobCard(
                company="Databricks",
                title="Associate Product Manager",
                location="Bellevue, WA",
                date="Oct 12",
                apply_url="https://databricks.com/careers/apply",
                is_direct_link=True,
            ),
            JobCard(
                company="Unknown Corp",
                title="PM Role",
                location="Remote",
                date="Oct 11",
                apply_url="https://jobright.ai/jobs/info/123",
                is_direct_link=False,
            ),
        ]
    
    def test_renders_html(self):
        html = render_html_email(self.test_cards, "New PM Jobs")
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("<html", html)
        self.assertIn("</html>", html)
    
    def test_contains_subject(self):
        html = render_html_email(self.test_cards, "New PM Jobs")
        self.assertIn("New PM Jobs", html)
    
    def test_contains_company_names(self):
        html = render_html_email(self.test_cards, "Test")
        self.assertIn("Databricks", html)
        self.assertIn("Unknown Corp", html)
    
    def test_contains_job_titles(self):
        html = render_html_email(self.test_cards, "Test")
        self.assertIn("Associate Product Manager", html)
        self.assertIn("PM Role", html)
    
    def test_contains_apply_urls(self):
        html = render_html_email(self.test_cards, "Test")
        self.assertIn("https://databricks.com/careers/apply", html)
        self.assertIn("https://jobright.ai/jobs/info/123", html)
    
    def test_contains_direct_badge(self):
        html = render_html_email(self.test_cards, "Test")
        self.assertIn("Direct", html)
    
    def test_contains_jobright_badge(self):
        html = render_html_email(self.test_cards, "Test")
        self.assertIn("Jobright", html)
    
    def test_contains_inline_styles(self):
        html = render_html_email(self.test_cards, "Test")
        self.assertIn("style=", html)
        self.assertIn("background-color", html)
    
    def test_job_count_display(self):
        html = render_html_email(self.test_cards, "Test")
        self.assertIn("2 new posting", html)
    
    def test_escapes_special_characters(self):
        malicious_card = JobCard(
            company="<script>alert('xss')</script>",
            title="Test & Title",
            location="\"Quoted\" Location",
            date="Today",
            apply_url="https://safe.com",
            is_direct_link=True,
        )
        html = render_html_email([malicious_card], "Test")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp;", html)


class RenderPlainTextEmailTests(unittest.TestCase):
    """Tests for plain text email rendering."""
    
    def setUp(self):
        self.test_cards = [
            JobCard(
                company="TestCo",
                title="Product Manager",
                location="NYC",
                date="Oct 12",
                apply_url="https://example.com",
                is_direct_link=True,
            ),
        ]
    
    def test_renders_text(self):
        text = render_plain_text_email(self.test_cards, "New Jobs")
        self.assertIsInstance(text, str)
        self.assertIn("New Jobs", text)
    
    def test_contains_job_info(self):
        text = render_plain_text_email(self.test_cards, "Test")
        self.assertIn("TestCo", text)
        self.assertIn("Product Manager", text)
        self.assertIn("NYC", text)
    
    def test_contains_apply_url(self):
        text = render_plain_text_email(self.test_cards, "Test")
        self.assertIn("https://example.com", text)
    
    def test_shows_link_type(self):
        text = render_plain_text_email(self.test_cards, "Test")
        self.assertIn("Direct", text)


class CreateJobCardsTests(unittest.TestCase):
    """Tests for job dict to JobCard conversion."""
    
    def test_creates_cards_from_jobs(self):
        jobs = [
            {
                "company": "Test",
                "title": "PM",
                "location": "NYC",
                "date": "Today",
                "source_url": "https://jobright.ai/123",
            }
        ]
        cards = create_job_cards_from_jobs(jobs)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].company, "Test")
    
    def test_uses_jobright_url_key(self):
        jobs = [
            {
                "company": "Test",
                "title": "PM",
                "location": "NYC",
                "date": "Today",
                "jobright_url": "https://jobright.ai/456",
            }
        ]
        cards = create_job_cards_from_jobs(jobs)
        self.assertEqual(cards[0].apply_url, "https://jobright.ai/456")


if __name__ == "__main__":
    unittest.main()
