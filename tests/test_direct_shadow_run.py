import unittest

from config import TARGETS
from ornitho.direct_shadow_run import combine_targets, parse_extra_targets


class DirectShadowRunTests(unittest.TestCase):
    def test_parse_extra_targets(self):
        self.assertEqual(parse_extra_targets("SH-HEI, hb-hb"), [("SH", "HEI"), ("HB", "HB")])

    def test_parse_extra_targets_rejects_invalid_value(self):
        with self.assertRaises(ValueError):
            parse_extra_targets("SH")

    def test_combine_targets_keeps_extra_targets_shadow_only(self):
        combined = combine_targets([("SH", "HEI"), TARGETS[0]])

        self.assertEqual(combined[: len(TARGETS)], TARGETS)
        self.assertIn(("SH", "HEI"), combined)
        self.assertEqual(combined.count(TARGETS[0]), 1)


if __name__ == "__main__":
    unittest.main()
