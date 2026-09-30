import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.resolver import (
    UrlResolver,
    ResolvedUrl,
    normalize_company_name,
    normalize_title,
    title_similarity,
    search_greenhouse,
    CACHE_TTL_SECONDS,
)


class NormalizationTests(unittest.TestCase):
    def test_normalize_company_name(self):
        cases = {
            "Stripe": "stripe",
            "Stripe, Inc.": "stripe",
            "Deutsche Bank": "deutschebank",
            "Cohen & Steers": "cohensteers",
            "84.51˚": "8451",
            "The Walt Disney Company": "thewaltdisney",
            "EMS Management & Consultants, Inc.": "emsmanagementconsultants",
        }
        for input_name, expected in cases.items():
            with self.subTest(input=input_name):
                self.assertEqual(normalize_company_name(input_name), expected)

    def test_normalize_title(self):
        cases = {
            "Associate Product Manager": "associate product manager",
            "Product Manager (Remote)": "product manager",
            "Sr. Product Manager - Technical": "sr product manager technical",
            "Product Manager, New Products": "product manager new products",
        }
        for input_title, expected in cases.items():
            with self.subTest(input=input_title):
                self.assertEqual(normalize_title(input_title), expected)


class SimilarityTests(unittest.TestCase):
    def test_identical_titles(self):
        self.assertEqual(title_similarity("Product Manager", "Product Manager"), 1.0)

    def test_similar_titles(self):
        score = title_similarity("Associate Product Manager", "Associate Product Manager, New Grad")
        self.assertGreater(score, 0.5)

    def test_different_titles(self):
        score = title_similarity("Product Manager", "Software Engineer")
        self.assertLess(score, 0.3)

    def test_empty_titles(self):
        self.assertEqual(title_similarity("", "Product Manager"), 0.0)
        self.assertEqual(title_similarity("Product Manager", ""), 0.0)


class GreenhouseSearchTests(unittest.TestCase):
    @patch("src.resolver._fetch_json")
    def test_search_success(self, mock_fetch):
        mock_fetch.return_value = {
            "jobs": [
                {
                    "title": "Associate Product Manager",
                    "absolute_url": "https://boards.greenhouse.io/test/jobs/123",
                    "location": {"name": "New York, NY"},
                },
                {
                    "title": "Software Engineer",
                    "absolute_url": "https://boards.greenhouse.io/test/jobs/456",
                    "location": {"name": "San Francisco, CA"},
                },
            ]
        }
        
        result = search_greenhouse("TestCompany", "Associate Product Manager")
        
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.url, "https://boards.greenhouse.io/test/jobs/123")
        self.assertEqual(result.ats, "Greenhouse")
        self.assertEqual(result.method, "greenhouse_api")

    @patch("src.resolver._fetch_json")
    def test_search_no_board(self, mock_fetch):
        mock_fetch.return_value = None
        
        result = search_greenhouse("NonExistentCompany", "Product Manager")
        
        self.assertEqual(result.status, "unresolved")
        self.assertIsNone(result.url)

    @patch("src.resolver._fetch_json")
    def test_search_no_matching_title(self, mock_fetch):
        mock_fetch.return_value = {
            "jobs": [
                {
                    "title": "Software Engineer",
                    "absolute_url": "https://boards.greenhouse.io/test/jobs/456",
                }
            ]
        }
        
        result = search_greenhouse("TestCompany", "Product Manager")
        
        self.assertEqual(result.status, "unresolved")


class UrlResolverTests(unittest.TestCase):
    def test_non_jobright_url_passthrough(self):
        resolver = UrlResolver()
        result = resolver.resolve(
            company="Stripe",
            title="Product Manager",
            source_url="https://boards.greenhouse.io/stripe/jobs/123"
        )
        
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.url, "https://boards.greenhouse.io/stripe/jobs/123")
        self.assertEqual(result.ats, "Greenhouse")
        self.assertEqual(result.method, "none")

    @patch("src.resolver.search_greenhouse")
    def test_jobright_url_resolution(self, mock_search):
        mock_search.return_value = ResolvedUrl(
            url="https://boards.greenhouse.io/test/jobs/123",
            ats="Greenhouse",
            status="resolved",
            method="greenhouse_api"
        )
        
        resolver = UrlResolver()
        result = resolver.resolve(
            company="TestCompany",
            title="Product Manager",
            source_url="https://jobright.ai/jobs/info/abc123"
        )
        
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.url, "https://boards.greenhouse.io/test/jobs/123")
        mock_search.assert_called_once()

    def test_caching(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            
            with patch("src.resolver.search_greenhouse") as mock_search:
                mock_search.return_value = ResolvedUrl(
                    url="https://boards.greenhouse.io/test/jobs/123",
                    ats="Greenhouse",
                    status="resolved",
                    method="greenhouse_api"
                )
                
                resolver = UrlResolver(cache_path=cache_path)
                result1 = resolver.resolve(
                    company="TestCompany",
                    title="Product Manager",
                    source_url="https://jobright.ai/jobs/info/abc123"
                )
                
                self.assertEqual(mock_search.call_count, 1)
                
                result2 = resolver.resolve(
                    company="TestCompany",
                    title="Product Manager",
                    source_url="https://jobright.ai/jobs/info/abc123"
                )
                
                self.assertEqual(mock_search.call_count, 1)
                self.assertEqual(result2.method, "cache")
                self.assertEqual(result2.url, result1.url)

    def test_cache_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            
            with patch("src.resolver.search_greenhouse") as mock_search:
                mock_search.return_value = ResolvedUrl(
                    url="https://boards.greenhouse.io/test/jobs/123",
                    ats="Greenhouse",
                    status="resolved",
                    method="greenhouse_api"
                )
                
                resolver1 = UrlResolver(cache_path=cache_path)
                resolver1.resolve(
                    company="TestCompany",
                    title="Product Manager",
                    source_url="https://jobright.ai/jobs/info/abc123"
                )
            
            resolver2 = UrlResolver(cache_path=cache_path)
            with patch("src.resolver.search_greenhouse") as mock_search2:
                result = resolver2.resolve(
                    company="TestCompany",
                    title="Product Manager",
                    source_url="https://jobright.ai/jobs/info/abc123"
                )
                
                mock_search2.assert_not_called()
                self.assertEqual(result.method, "cache")

    @patch("src.resolver.search_greenhouse")
    def test_resolution_error_handling(self, mock_search):
        mock_search.side_effect = Exception("Network error")
        
        resolver = UrlResolver()
        result = resolver.resolve(
            company="TestCompany",
            title="Product Manager",
            source_url="https://jobright.ai/jobs/info/abc123"
        )
        
        self.assertEqual(result.status, "error")
        self.assertIsNone(result.url)

    @patch("src.resolver.search_greenhouse")
    def test_batch_resolution(self, mock_search):
        mock_search.return_value = ResolvedUrl(
            url="https://boards.greenhouse.io/test/jobs/123",
            ats="Greenhouse",
            status="resolved",
            method="greenhouse_api"
        )
        
        jobs = [
            {"company": "Company1", "title": "PM1", "source_url": "https://jobright.ai/jobs/info/1"},
            {"company": "Company2", "title": "PM2", "source_url": "https://jobright.ai/jobs/info/2"},
        ]
        
        resolver = UrlResolver()
        results = resolver.resolve_batch(jobs, rate_limit=0)
        
        self.assertEqual(len(results), 2)
        for job, result in results:
            self.assertEqual(result.status, "resolved")


class CacheExpirationTests(unittest.TestCase):
    def test_cache_expiration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            
            expired_cache = {
                "version": 1,
                "entries": {
                    "abc123": {
                        "url": "https://old.url",
                        "ats": "Greenhouse",
                        "status": "resolved",
                        "method": "greenhouse_api",
                        "cached_at": time.time() - CACHE_TTL_SECONDS - 1,
                    }
                }
            }
            cache_path.write_text(json.dumps(expired_cache))
            
            with patch("src.resolver.search_greenhouse") as mock_search:
                mock_search.return_value = ResolvedUrl(
                    url="https://new.url",
                    ats="Greenhouse",
                    status="resolved",
                    method="greenhouse_api"
                )
                
                resolver = UrlResolver(cache_path=cache_path)
                result = resolver.resolve(
                    company="TestCompany",
                    title="Product Manager",
                    source_url="https://jobright.ai/jobs/info/abc123"
                )
                
                mock_search.assert_called_once()
                self.assertEqual(result.url, "https://new.url")


if __name__ == "__main__":
    unittest.main()
