from pathlib import Path
import tempfile
import unittest

from ornitho.state import (
    compare_current_records,
    empty_state,
    identify_new_records,
    load_state,
    record_key,
    save_state,
    update_state,
    validate_state,
)


def sample_record(species="Test Bird", detail=""):
    return {
        "date": "Saturday, June 27th, 2026",
        "location": "Test Marsh",
        "count": "1",
        "species": species,
        "scientific": "Avis testus",
        "detail": detail,
    }


class StateTests(unittest.TestCase):
    def test_load_missing_state_returns_empty_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = load_state(Path(tmpdir, "missing.json"))

        self.assertEqual(state, empty_state())

    def test_save_and_load_state_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir, "state.json")
            state = update_state(empty_state(), "default", [("HB-HB", [sample_record()])])

            save_state(state, path)
            loaded = load_state(path)

        self.assertEqual(loaded, state)

    def test_identify_new_records_excludes_seen_records(self):
        old_record = sample_record("Seen Bird")
        new_record = sample_record("New Bird")
        state = update_state(empty_state(), "default", [("NI-OHZ", [old_record])])

        new_records = identify_new_records(
            state,
            "default",
            "NI-OHZ",
            [old_record, new_record],
        )

        self.assertEqual(new_records, [new_record])

    def test_compare_current_records_is_scoped_by_monitor_and_target(self):
        record = sample_record()
        state = update_state(empty_state(), "default", [("NI-OHZ", [record])])

        self.assertEqual(compare_current_records(state, "default", [("NI-OHZ", [record])]), [("NI-OHZ", [])])
        self.assertEqual(compare_current_records(state, "other", [("NI-OHZ", [record])]), [("NI-OHZ", [record])])
        self.assertEqual(compare_current_records(state, "default", [("HB-HB", [record])]), [("HB-HB", [record])])

    def test_record_key_ignores_dict_order(self):
        record = sample_record()
        reordered = {
            "detail": record["detail"],
            "scientific": record["scientific"],
            "species": record["species"],
            "count": record["count"],
            "location": record["location"],
            "date": record["date"],
        }

        self.assertEqual(record_key(record), record_key(reordered))

    def test_save_state_replaces_existing_file_atomically(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir, "state.json")
            path.write_text("previous", encoding="utf-8")
            state = update_state(empty_state(), "default", [("HB-HB", [sample_record()])])

            save_state(state, path)

            self.assertEqual(load_state(path), state)
            self.assertFalse(list(Path(tmpdir).glob("tmp*")))

    def test_validate_state_rejects_unknown_schema_version(self):
        with self.assertRaisesRegex(RuntimeError, "Unsupported state schema version"):
            validate_state({"schema_version": 999, "monitors": {}})

    def test_validate_state_normalizes_duplicate_seen_keys(self):
        state = {
            "schema_version": 1,
            "monitors": {
                "default": {
                    "targets": {
                        "HB-HB": {
                            "seen_record_keys": ["b", "a", "b"],
                        },
                    },
                },
            },
        }

        normalized = validate_state(state)

        self.assertEqual(normalized["monitors"]["default"]["targets"]["HB-HB"]["seen_record_keys"], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
