import json
import unittest
from urllib.parse import parse_qs, urlsplit

from ornitho.direct_shadow_compare import compare_records
from ornitho.direct_scraper import (
    DirectOrnithoScraper,
    apply_categories,
    find_target_control,
    observation_page_url,
    row_to_record,
)


def district_onclick(code, title, selected_suffix):
    return (
        "buildUrl(event, "
        "'index.php?m_id=5&sp_SChoice=category&sp_Cat[rare]=1&sp_Cat[veryrare]=0"
        f"&sp_cC=-000{selected_suffix}', "
        "'index.php?m_id=5&sp_SChoice=category&sp_Cat[rare]=1&sp_Cat[veryrare]=0"
        f"&sp_cC=-___{selected_suffix}')"
    )


class DirectScraperTests(unittest.TestCase):
    def test_hb_hb_duplicate_label_uses_district_level_control(self):
        html = """
        <div onclick="buildUrl(event, 'index.php?m_id=5&sp_PChoice=canton&sp_cC=0000')">HB</div>
        <div title="Bremen (Freie Hansestadt)"
             onclick="buildUrl(event,
             'index.php?m_id=5&sp_SChoice=category&sp_cC=-0004000',
             'index.php?m_id=5&sp_SChoice=category&sp_cC=-___W___')">HB</div>
        """

        control = find_target_control(html, ("HB", "HB"))

        self.assertEqual(control.title, "Bremen (Freie Hansestadt)")
        self.assertIn("sp_cC=-0004000", control.document_url)

    def test_resolves_ni_dh_district_control(self):
        html = f"""
        <div title="Diepholz" onclick="{district_onclick("DH", "Diepholz", "Z")}">DH</div>
        """

        control = find_target_control(html, ("NI", "DH"))

        self.assertEqual(control.title, "Diepholz")
        self.assertIn("sp_cC=-000Z", control.document_url)

    def test_category_flags_support_rare_and_very_rare(self):
        url = "https://www.ornitho.de/index.php?m_id=5&sp_Cat[rare]=0&sp_Cat[veryrare]=0&sp_Cat[common]=1"

        updated = apply_categories(url, ("rare", "veryrare"))
        query = parse_qs(urlsplit(updated).query)

        self.assertEqual(query["sp_Cat[rare]"], ["1"])
        self.assertEqual(query["sp_Cat[veryrare]"], ["1"])
        self.assertEqual(query["sp_Cat[common]"], ["0"])

    def test_observation_url_points_to_json_endpoint_page(self):
        url = observation_page_url("https://www.ornitho.de/index.php?m_id=5&sp_cC=-abc", 3)
        query = parse_qs(urlsplit(url).query)

        self.assertEqual(query["m_id"], ["1351"])
        self.assertEqual(query["content"], ["observations_by_page"])
        self.assertEqual(query["mp_current_page"], ["3"])
        self.assertEqual(query["txid"], ["3"])
        self.assertEqual(query["langu"], ["en"])

    def test_row_to_record_maps_existing_shape_and_detail(self):
        record = row_to_record(
            {
                "listTop": {"title": "Saturday, June 27th, 2026"},
                "listSubmenu": {"title": "Example Marsh [123] / Exampletown"},
                "species_array": {"name": "Caspian Tern", "latin_name": "Hydroprogne caspia"},
                "birds_count_raw": "1",
                "date_raw": "2026-06-27T00:00:00+02:00",
                "remarks": [{"title": "Detail", "content": "feeding offshore"}],
            }
        )

        self.assertEqual(
            record,
            {
                "date": "Saturday, June 27th, 2026",
                "location": "Example Marsh [123] / Exampletown",
                "count": "1",
                "species": "Caspian Tern",
                "scientific": "Hydroprogne caspia",
                "detail": "Detail feeding offshore",
                "rarity": "",
            },
        )

    def test_row_to_record_prefers_display_species_name(self):
        record = row_to_record(
            {
                "listSubmenu": {"title": "Example"},
                "species_array": {"name": "Little Egret", "latin_name": "Egretta garzetta"},
                "sighting_detail_short_raw": "Little Egrets",
                "birds_count_raw": "3",
                "date_raw": "2026-06-30T00:00:00+02:00",
            }
        )

        self.assertEqual(record["species"], "Little Egrets")

    def test_paginates_until_finished(self):
        calls = []

        def fetch(url):
            calls.append(url)
            page = parse_qs(urlsplit(url).query)["mp_current_page"][0]
            if page == "1":
                return json.dumps(
                    {
                        "data": [
                            {
                                "listSubmenu": {"title": "A"},
                                "species_array": {"name": "Black Kite", "latin_name": "Milvus migrans"},
                                "birds_count_raw": "1",
                                "date_raw": "2026-06-30T00:00:00+02:00",
                            }
                        ],
                        "data_is_finished": 0,
                    }
                )
            return json.dumps({"data": [], "data_is_finished": 1})

        result = DirectOrnithoScraper(fetch).fetch_records_for_document_url(
            "https://www.ornitho.de/index.php?m_id=5&sp_SChoice=category&sp_cC=-abc"
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(result.stats.pages_fetched, 2)
        self.assertEqual(result.stats.records_parsed, 1)
        self.assertEqual(result.records[0]["species"], "Black Kite")

    def test_empty_target_page_returns_no_records_with_stats(self):
        def fetch(_url):
            return json.dumps({"data": [], "data_is_finished": 1})

        result = DirectOrnithoScraper(fetch).fetch_records_for_document_url(
            "https://www.ornitho.de/index.php?m_id=5&sp_SChoice=category&sp_cC=-abc"
        )

        self.assertEqual(result.records, [])
        self.assertEqual(result.stats.pages_fetched, 1)
        self.assertEqual(result.stats.records_parsed, 0)

    def test_comparison_tool_reports_missing_and_extra_records(self):
        expected = [{"date": "D", "location": "L", "species": "A", "scientific": "S", "count": "1"}]
        actual = [{"date": "D", "location": "L", "species": "B", "scientific": "S", "count": "1"}]

        comparison = compare_records(expected, actual)

        self.assertFalse(comparison["matches"])
        self.assertEqual(comparison["expected_count"], 1)
        self.assertEqual(comparison["actual_count"], 1)
        self.assertEqual(len(comparison["missing"]), 1)
        self.assertEqual(len(comparison["extra"]), 1)


if __name__ == "__main__":
    unittest.main()
