"""Tests for Jobright browser resolver."""
import unittest
from unittest.mock import MagicMock, patch

from src.jobright_browser import (
    JobrightResolvedUrl,
    _detect_ats,
    _is_valid_apply_url,
    extract_job_id,
)


class ExtractJobIdTests(unittest.TestCase):
    """Tests for extract_job_id function."""
    
    def test_valid_url(self):
        url = "https://jobright.ai/jobs/info/6aa02a5ba2266b538d22e7ca"
        self.assertEqual(extract_job_id(url), "6aa02a5ba2266b538d22e7ca")
    
    def test_url_with_query_params(self):
        url = "https://jobright.ai/jobs/info/6aa02a5ba2266b538d22e7ca?ref=search"
        self.assertEqual(extract_job_id(url), "6aa02a5ba2266b538d22e7ca")
    
    def test_invalid_url(self):
        url = "https://jobright.ai/other/path"
        self.assertIsNone(extract_job_id(url))
    
    def test_non_jobright_url(self):
        url = "https://greenhouse.io/jobs/123"
        self.assertIsNone(extract_job_id(url))


class DetectAtsTests(unittest.TestCase):
    """Tests for ATS detection from URLs."""
    
    def test_greenhouse_url(self):
        self.assertEqual(_detect_ats("https://boards.greenhouse.io/company/jobs/123"), "Greenhouse")
        self.assertEqual(_detect_ats("https://job-boards.greenhouse.io/company/jobs/123"), "Greenhouse")
    
    def test_workday_url(self):
        self.assertEqual(_detect_ats("https://company.wd5.myworkdayjobs.com/en-US/careers/job/123"), "Workday")
    
    def test_lever_url(self):
        self.assertEqual(_detect_ats("https://jobs.lever.co/company/abc123"), "Lever")
    
    def test_ashby_url(self):
        self.assertEqual(_detect_ats("https://jobs.ashbyhq.com/company/abc123"), "Ashby")
    
    def test_icims_url(self):
        self.assertEqual(_detect_ats("https://careers-company.icims.com/jobs/123"), "iCIMS")
    
    def test_smartrecruiters_url(self):
        self.assertEqual(_detect_ats("https://jobs.smartrecruiters.com/Company/123"), "SmartRecruiters")
    
    def test_company_url(self):
        self.assertEqual(_detect_ats("https://careers.example.com/jobs/123"), "Company")


class ValidApplyUrlTests(unittest.TestCase):
    """Tests for apply URL validation."""
    
    def test_valid_greenhouse_url(self):
        self.assertTrue(_is_valid_apply_url("https://boards.greenhouse.io/company/jobs/123"))
    
    def test_valid_company_url(self):
        self.assertTrue(_is_valid_apply_url("https://careers.example.com/apply"))
    
    def test_invalid_jobright_url(self):
        self.assertFalse(_is_valid_apply_url("https://jobright.ai/jobs/info/123"))
    
    def test_invalid_linkedin_url(self):
        self.assertFalse(_is_valid_apply_url("https://www.linkedin.com/jobs/view/123"))
    
    def test_invalid_indeed_url(self):
        self.assertFalse(_is_valid_apply_url("https://www.indeed.com/viewjob?jk=123"))
    
    def test_invalid_glassdoor_url(self):
        self.assertFalse(_is_valid_apply_url("https://www.glassdoor.com/job-listing/123"))
    
    def test_empty_url(self):
        self.assertFalse(_is_valid_apply_url(""))
    
    def test_non_http_url(self):
        self.assertFalse(_is_valid_apply_url("javascript:void(0)"))


class JobrightResolvedUrlTests(unittest.TestCase):
    """Tests for JobrightResolvedUrl dataclass."""
    
    def test_resolved_result(self):
        result = JobrightResolvedUrl(
            url="https://boards.greenhouse.io/company/jobs/123",
            ats="Greenhouse",
            status="resolved",
            method="browser_jobright_manual_apply"
        )
        self.assertEqual(result.url, "https://boards.greenhouse.io/company/jobs/123")
        self.assertEqual(result.ats, "Greenhouse")
        self.assertEqual(result.status, "resolved")
        self.assertIsNone(result.blocker_details)
    
    def test_login_required_result(self):
        result = JobrightResolvedUrl(
            url=None,
            ats="Unknown",
            status="login_required",
            method="none",
            blocker_details="Login required"
        )
        self.assertIsNone(result.url)
        self.assertEqual(result.status, "login_required")
        self.assertEqual(result.blocker_details, "Login required")


if __name__ == "__main__":
    unittest.main()
