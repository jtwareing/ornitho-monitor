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

    def test_current_parser_reads_only_first_record_under_date_heading(self):
        text = """
        Tuesday, June 30th, 2026
        First Marsh / Example (SH, HEI)
        1
        Corn Bunting
        (Emberiza calandra)
        Second Marsh / Example (SH, HEI)
        2
        Gull-billed Terns
        (Gelochelidon nilotica)
        """

        records = parse_records(text)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["species"], "Corn Bunting")


if __name__ == "__main__":
    unittest.main()
