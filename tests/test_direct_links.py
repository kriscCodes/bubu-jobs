"""Tests for direct link lookup."""
import json
import tempfile
import unittest
from pathlib import Path

from src.direct_links import (
    DirectLink,
    DirectLinkLookup,
    _normalize_company,
    _normalize_text,
    _title_similarity,
    _location_match_score,
    get_direct_link,
)


class NormalizationTests(unittest.TestCase):
    """Tests for text normalization functions."""
    
    def test_normalize_text(self):
        self.assertEqual(_normalize_text("Hello, World!"), "hello world")
        self.assertEqual(_normalize_text("  Multiple   Spaces  "), "multiple spaces")
        self.assertEqual(_normalize_text("Special–Chars"), "special chars")
    
    def test_normalize_company(self):
        self.assertEqual(_normalize_company("Example Inc."), "example")
        self.assertEqual(_normalize_company("Test Corp"), "test")
        self.assertEqual(_normalize_company("Acme Company"), "acme")
        self.assertEqual(_normalize_company("Tech Holdings"), "tech")
        self.assertEqual(_normalize_company("Databricks"), "databricks")


class SimilarityTests(unittest.TestCase):
    """Tests for similarity scoring functions."""
    
    def test_title_similarity_identical(self):
        score = _title_similarity("Product Manager", "Product Manager")
        self.assertEqual(score, 1.0)
    
    def test_title_similarity_similar(self):
        score = _title_similarity(
            "Associate Product Manager",
            "Associate Product Manager, New Grad"
        )
        self.assertGreater(score, 0.5)
    
    def test_title_similarity_different(self):
        score = _title_similarity(
            "Software Engineer",
            "Product Manager"
        )
        self.assertLess(score, 0.5)
    
    def test_title_similarity_empty(self):
        self.assertEqual(_title_similarity("", "Product Manager"), 0.0)
        self.assertEqual(_title_similarity("Product Manager", ""), 0.0)
    
    def test_location_match_identical(self):
        self.assertEqual(_location_match_score("New York, NY", "New York, NY"), 1.0)
    
    def test_location_match_partial(self):
        score = _location_match_score("New York, NY", "New York, NY, United States")
        self.assertGreater(score, 0.5)
    
    def test_location_match_different(self):
        score = _location_match_score("San Francisco, CA", "New York, NY")
        self.assertLess(score, 0.5)


class DirectLinkLookupTests(unittest.TestCase):
    """Tests for DirectLinkLookup class."""
    
    def setUp(self):
        self.test_data = [
            {
                "company": "Databricks",
                "title": "Associate Product Manager, New Grad (2027 Start)",
                "location": "Bellevue, WA, United States",
                "status": "resolved",
                "direct_url": "https://databricks.com/careers/job?gh_jid=7586263002",
                "jobright": "https://jobright.ai/jobs/info/123",
                "note": "Exact title on Greenhouse"
            },
            {
                "company": "Roblox",
                "title": "[2027] Associate Product Manager, Early Career",
                "location": "San Mateo, CA, United States",
                "status": "resolved",
                "direct_url": "https://careers.roblox.com/jobs/8143976",
                "jobright": "https://jobright.ai/jobs/info/456",
                "note": "Greenhouse API"
            },
            {
                "company": "CWILL",
                "title": "Order Tracking Product Management Trainee",
                "location": "Cary, NC, United States",
                "status": "unresolved",
                "note": "Role closed"
            }
        ]
        
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(self.test_data, self.temp_file)
        self.temp_file.close()
        
        self.lookup = DirectLinkLookup(Path(self.temp_file.name))
    
    def tearDown(self):
        Path(self.temp_file.name).unlink()
    
    def test_load_links(self):
        self.assertEqual(self.lookup.get_link_count(), 2)
    
    def test_lookup_exact_match(self):
        result = self.lookup.lookup(
            "Databricks",
            "Associate Product Manager, New Grad (2027 Start)",
            "Bellevue, WA, United States"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.company, "Databricks")
        self.assertIn("databricks.com", result.direct_url)
    
    def test_lookup_similar_title(self):
        result = self.lookup.lookup(
            "Databricks",
            "Associate Product Manager New Grad 2027",
            "Bellevue, WA"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.company, "Databricks")
    
    def test_lookup_no_match(self):
        result = self.lookup.lookup(
            "Unknown Company",
            "Unknown Role",
            "Unknown Location"
        )
        self.assertIsNone(result)
    
    def test_lookup_unresolved_excluded(self):
        result = self.lookup.lookup(
            "CWILL",
            "Order Tracking Product Management Trainee",
            "Cary, NC"
        )
        self.assertIsNone(result)
    
    def test_location_tiebreaker(self):
        data_with_duplicates = [
            {
                "company": "Instawork",
                "title": "Product Operations Analyst",
                "location": "San Francisco, CA, United States",
                "status": "resolved",
                "direct_url": "https://greenhouse.io/instawork/sf",
                "jobright": "https://jobright.ai/1",
                "note": "SF"
            },
            {
                "company": "Instawork",
                "title": "Product Operations Analyst",
                "location": "Chicago, IL, United States",
                "status": "resolved",
                "direct_url": "https://greenhouse.io/instawork/chicago",
                "jobright": "https://jobright.ai/2",
                "note": "Chicago"
            }
        ]
        
        temp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(data_with_duplicates, temp)
        temp.close()
        
        lookup = DirectLinkLookup(Path(temp.name))
        
        sf_result = lookup.lookup("Instawork", "Product Operations Analyst", "San Francisco, CA")
        self.assertIn("sf", sf_result.direct_url)
        
        chicago_result = lookup.lookup("Instawork", "Product Operations Analyst", "Chicago, IL")
        self.assertIn("chicago", chicago_result.direct_url)
        
        Path(temp.name).unlink()


class GetDirectLinkTests(unittest.TestCase):
    """Tests for the get_direct_link convenience function."""
    
    def test_returns_none_on_error(self):
        result = get_direct_link("Unknown", "Unknown", "Unknown")
        self.assertTrue(result is None or isinstance(result, DirectLink))


if __name__ == "__main__":
    unittest.main()
