import unittest

from ornitho.parser import parse_records


class ParserTests(unittest.TestCase):
    def test_current_parser_ignores_count_ranges(self):
        text = """
        Tuesday, June 30th, 2026
        Example Marsh / Example (SH, HEI)
        2-3
        Little Egrets
        (Egretta garzetta)
        """

        self.assertEqual(parse_records(text), [])


if __name__ == "__main__":
    unittest.main()
