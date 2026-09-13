import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError
from src.sources.jobright import parse_readme, fetch_readme

HEADER = "| Company | Job Title | Location | Work Model | Date Posted |\n| --- | --- | --- | --- | --- |\n"
ROW = "| **[Acme](https://acme.com)** | **[Associate Product Manager](https://jobright.ai/jobs/123?utm_source=x)** | NY | Hybrid | Sep 11 |\n"


class ParserTests(unittest.TestCase):
    def test_real_format_and_continuation(self):
        text = HEADER + ROW + "| ↳ | [Product Analyst](https://boards.greenhouse.io/acme/jobs/42) | Boston<br>NY | Remote | Sep 12 |"
        jobs = parse_readme(text)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[1].company, "Acme")
        self.assertEqual(jobs[0].source_url, "https://jobright.ai/jobs/123")
        self.assertIsNone(jobs[0].canonical_apply_url)
        self.assertEqual(jobs[1].ats, "Greenhouse")
        self.assertEqual(jobs[1].location, "Boston, NY")
        self.assertEqual(jobs[0].date_posted, "Sep 11")

    def test_escaped_pipe_entities_parentheses(self):
        row = ROW.replace("Acme](", "Acme &amp; Co](").replace("Manager](", r"Manager \| Platform](").replace("/123?", "/123(test)?")
        job = parse_readme(HEADER + row)[0]
        self.assertEqual(job.company, "Acme & Co")
        self.assertIn("| Platform", job.title)
        self.assertIn("123(test)", job.source_url)

    def test_bracketed_year_in_title(self):
        job = parse_readme(HEADER + ROW.replace("Associate Product Manager", "[2027] Associate Product Manager"))[0]
        self.assertEqual(job.title, "[2027] Associate Product Manager")

    def test_explicit_apply_column(self):
        header = HEADER.splitlines()[0].rstrip() + " Apply |\n"
        row = ROW.strip() + " [Apply](https://jobs.lever.co/acme/123) |"
        job = parse_readme(header + row)[0]
        self.assertEqual(job.ats, "Lever")
        self.assertEqual(job.canonical_apply_url, "https://jobs.lever.co/acme/123")

    def test_fail_closed(self):
        for text in ("changed schema", HEADER + ROW.replace("**[Acme](https://acme.com)**", "↳"),
                     HEADER + "| Acme | missing columns |", HEADER + ROW.replace("**[Associate Product Manager](https://jobright.ai/jobs/123?utm_source=x)**", "No URL")):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_readme(text)

    def test_empty_table(self):
        self.assertEqual(parse_readme(HEADER), [])

    def test_company_does_not_leak_between_tables(self):
        with self.assertRaises(ValueError):
            parse_readme(HEADER + ROW + "\n" + HEADER + ROW.replace("**[Acme](https://acme.com)**", "↳"))


class FetchTests(unittest.TestCase):
    @patch("src.sources.jobright.urlopen")
    def test_etag_and_timeout(self, open_url):
        response = MagicMock()
        response.read.return_value = b"README"
        response.headers = {"ETag": '"new"'}
        open_url.return_value.__enter__.return_value = response
        result = fetch_readme('"old"')
        self.assertEqual(result.text, "README")
        self.assertEqual(result.etag, '"new"')
        self.assertEqual(open_url.call_args.args[0].get_header("If-none-match"), '"old"')
        self.assertEqual(open_url.call_args.kwargs["timeout"], 30)

    @patch("src.sources.jobright.urlopen")
    def test_not_modified(self, open_url):
        open_url.side_effect = HTTPError("url", 304, "unchanged", {}, None)
        self.assertIsNone(fetch_readme('"old"').text)

    @patch("src.sources.jobright.time.sleep")
    @patch("src.sources.jobright.urlopen")
    def test_bounded_retries(self, open_url, sleep):
        for error in (URLError("offline"), HTTPError("url", 503, "busy", {}, None)):
            open_url.reset_mock()
            open_url.side_effect = error
            with self.assertRaises((URLError, HTTPError)):
                fetch_readme()
            self.assertEqual(open_url.call_count, 3)

    @patch("src.sources.jobright.urlopen")
    def test_no_retry_on_404(self, open_url):
        open_url.side_effect = HTTPError("url", 404, "missing", {}, None)
        with self.assertRaises(HTTPError):
            fetch_readme()
        self.assertEqual(open_url.call_count, 1)
