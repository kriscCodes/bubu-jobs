import unittest
from src.filters import is_relevant


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
                      "Product Operations Leader", "Sales Manager", "Product Managerial Assistant"):
            with self.subTest(title=title):
                self.assertFalse(is_relevant(title))

    def test_custom_keywords_and_word_boundaries(self):
        self.assertTrue(is_relevant("Product Management Internship"))
        self.assertTrue(is_relevant("Widget Expert", ("widget",), ("senior",)))
        self.assertFalse(is_relevant("Senior Widget Expert", ("widget",), ("senior",)))
