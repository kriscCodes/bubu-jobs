import unittest
from src.filters import has_us_location, is_relevant, is_us_location


class FilterTests(unittest.TestCase):
    def test_accepted(self):
        for title in ("Associate Product Manager, Strategic Accounts", "Product Manager",
                      "Junior Product Manager", "Graduate Product Manager", "Product Analyst",
                      "Product Operations", "Product Strategy", "Product Management Intern",
                      "ASSOCIATE PRODUCT-MANAGER"):
            with self.subTest(title=title):
                self.assertTrue(is_relevant(title))

    def test_rejected(self):
        for title in ("Product Demonstrator", "Senior Product Manager", "Sr. Product Manager",
                      "Principal Product Manager", "Lead Product Manager", "Director of Product Management",
                      "Technician", "Retail Educator", "Product Development Scientist",
                      "Product Operations Leader", "Sales Manager", "Product Managerial Assistant",
                      "Sr PM", "Sr. PM", "Staff Product Manager"):
            with self.subTest(title=title):
                self.assertFalse(is_relevant(title))

    def test_senior_associate_is_allowed(self):
        for title in (
            "Senior Associate, Product Manager - Business Cards",
            "Senior Associate Product Manager - Enterprise AI",
            "Senior Associate, Product Management",
            "Sr Associate Product Manager",
            "Sr. Associate, Product Manager",
        ):
            with self.subTest(title=title):
                self.assertTrue(is_relevant(title))

    def test_senior_associate_still_rejects_director_lead(self):
        self.assertFalse(is_relevant("Senior Associate Director of Product Management"))
        self.assertFalse(is_relevant("Lead Senior Associate Product Manager"))

    def test_custom_keywords_and_word_boundaries(self):
        self.assertTrue(is_relevant("Product Management Internship"))
        self.assertTrue(is_relevant("Widget Expert", ("widget",), ("senior",)))
        self.assertFalse(is_relevant("Senior Widget Expert", ("widget",), ("senior",)))
        self.assertTrue(is_relevant("Senior Associate Widget Expert", ("widget",), ("senior", "sr")))


class UsLocationTests(unittest.TestCase):
    def test_us_locations(self):
        for location in (
            "SF", "NYC", "San Mateo, CA", "Austin, TX", "Remote in USA", "Remote US",
            "United States", "USA IL Vernon Hills", "Boston, MA", "Nebraska",
            "Hybrid (Washington, DC - USA)", "Mountain View, CA, USA",
        ):
            with self.subTest(location=location):
                self.assertTrue(is_us_location(location), location)

    def test_non_us_locations(self):
        for location in (
            "London, UK", "Edinburgh, UK", "Toronto, ON, Canada", "Remote in Canada",
            "United Kingdom", "Reading, UK", "",
        ):
            with self.subTest(location=location):
                self.assertFalse(is_us_location(location), location)

    def test_at_least_one_us_location(self):
        self.assertTrue(has_us_location(["London, UK", "NYC"]))
        self.assertTrue(has_us_location(["Remote in USA", "Remote in Canada"]))
        self.assertFalse(has_us_location(["London, UK", "Edinburgh, UK"]))
        self.assertTrue(has_us_location("Boston, Massachusetts, USA; Dallas, Texas, USA"))
