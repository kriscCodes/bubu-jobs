import unittest
from src.ats import detect_ats


class AtsTests(unittest.TestCase):
    def test_domains(self):
        for host, expected in {
            "boards.greenhouse.io": "Greenhouse", "job-boards.greenhouse.io": "Greenhouse",
            "company.wd5.myworkdayjobs.com": "Workday", "wd1.myworkdaysite.com": "Workday",
            "jobs.lever.co": "Lever", "jobs.ashbyhq.com": "Ashby",
            "careers-company.icims.com": "iCIMS", "jobs.smartrecruiters.com": "SmartRecruiters",
            "jobright.ai": "Unknown", "greenhouse.io.evil.com": "Unknown",
            "notlever.co": "Unknown",
        }.items():
            with self.subTest(host=host):
                self.assertEqual(detect_ats(f"https://{host}/jobs/123"), expected)
        self.assertEqual(detect_ats("https://example.com/?next=jobs.lever.co"), "Unknown")

    def test_custom_domain_greenhouse(self):
        """Greenhouse hosted on custom company domains with gh_jid parameter."""
        urls = [
            "https://databricks.com/company/careers/open-positions/job?gh_jid=7586263002",
            "https://careers.roblox.com/jobs/8143976?gh_jid=8143976",
            "https://www.trepp.com/joining-trepp?gh_jid=8187266",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(detect_ats(url), "Greenhouse")

    def test_query_param_not_spoofable(self):
        """Ensure domain detection takes precedence for actual ATS domains."""
        self.assertEqual(
            detect_ats("https://boards.greenhouse.io/jobs/123?gh_jid=456"),
            "Greenhouse"
        )
