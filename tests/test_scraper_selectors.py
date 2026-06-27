import sys
import types
import unittest

try:
    import bs4  # noqa: F401
except ModuleNotFoundError:
    bs4 = types.ModuleType("bs4")
    bs4.BeautifulSoup = lambda html, parser: None
    sys.modules["bs4"] = bs4

try:
    import playwright.sync_api  # noqa: F401
except ModuleNotFoundError:
    playwright = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.TimeoutError = TimeoutError
    playwright.sync_api = sync_api
    sys.modules["playwright"] = playwright
    sys.modules["playwright.sync_api"] = sync_api

from ornitho.scraper import choose_below_reference, exact_text_pattern


class ScraperSelectorTests(unittest.TestCase):
    def test_duplicate_label_selects_candidate_below_state(self):
        reference_box = {"y": 100}
        candidate_boxes = [
            {"y": 100},
            {"y": 160},
            {"y": 240},
        ]

        self.assertEqual(choose_below_reference(reference_box, candidate_boxes), 1)

    def test_duplicate_label_without_lower_candidate_is_ambiguous(self):
        reference_box = {"y": 100}
        candidate_boxes = [
            {"y": 80},
            {"y": 100},
        ]

        self.assertIsNone(choose_below_reference(reference_box, candidate_boxes))

    def test_exact_text_pattern_allows_surrounding_whitespace(self):
        pattern = exact_text_pattern("HB")

        self.assertRegex(" HB ", pattern)
        self.assertNotRegex("HBB", pattern)


if __name__ == "__main__":
    unittest.main()
