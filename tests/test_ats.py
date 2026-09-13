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
