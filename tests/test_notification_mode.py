from pathlib import Path
import sys
import tempfile
import types
import unittest


def install_dependency_stubs():
    if "bs4" not in sys.modules:
        bs4 = types.ModuleType("bs4")
        bs4.BeautifulSoup = lambda html, parser: None
        sys.modules["bs4"] = bs4

    if "playwright.sync_api" not in sys.modules:
        playwright = types.ModuleType("playwright")
        sync_api = types.ModuleType("playwright.sync_api")
        sync_api.TimeoutError = TimeoutError
        sync_api.sync_playwright = lambda: None
        playwright.sync_api = sync_api
        sys.modules["playwright"] = playwright
        sys.modules["playwright.sync_api"] = sync_api


def sample_record(species="Test Bird"):
    return {
        "date": "Saturday, June 27th, 2026",
        "location": "Test Marsh",
        "count": "1",
        "species": species,
        "scientific": "Avis testus",
        "detail": "",
    }


def sample_record_with_location(species, location):
    record = sample_record(species=species)
    record["location"] = location
    return record


class NotificationModeTests(unittest.TestCase):
    def run_notify_monitor(self, initial_state, records, monitor_name="test"):
        install_dependency_stubs()
        import config
        import ornitho.main as main

        sent = []

        def fake_check_target_with_retry(browser, state, district, attempts, wait_seconds):
            return records

        def fake_send_email(report, dry_run=False, email_to=None, subject=None):
            sent.append((report, dry_run, email_to, subject))

        with tempfile.TemporaryDirectory() as tmpdir:
            original_out = main.OUT
            original_state_path = main.STATE_PATH
            original_dry_run = main.DRY_RUN
            original_check = main.check_target_with_retry
            original_send = main.send_email
            try:
                main.OUT = Path(tmpdir)
                main.STATE_PATH = Path(tmpdir, "state.json")
                main.DRY_RUN = False
                main.check_target_with_retry = fake_check_target_with_retry
                main.send_email = fake_send_email

                monitor = config.Monitor(
                    name=monitor_name,
                    email_to="profile@example.test",
                    targets=[("HB", "HB")],
                )
                updated_state = main.run_monitor(
                    object(),
                    monitor,
                    initial_state,
                    mode=main.NOTIFY_MODE,
                    persist_state=True,
                )
                report = Path(tmpdir, "multi_report.txt").read_text(encoding="utf-8")
            finally:
                main.OUT = original_out
                main.STATE_PATH = original_state_path
                main.DRY_RUN = original_dry_run
                main.check_target_with_retry = original_check
                main.send_email = original_send

        return updated_state, sent, report

    def test_no_new_records_sends_no_email(self):
        from ornitho.state import empty_state, update_state

        record = sample_record()
        state = update_state(empty_state(), "test", [("HB-HB", [record])])

        updated_state, sent, report = self.run_notify_monitor(state, [record])

        self.assertEqual(sent, [])
        self.assertIn("No new rare records.", report)
        self.assertEqual(updated_state, state)

    def test_one_new_record_sends_one_notification(self):
        from ornitho.state import empty_state

        record = sample_record_with_location(
            "Black Kite",
            "Leester Marsch NW [2918_4_50s] / Weyhe (NI, DH)",
        )
        record["scientific"] = "Milvus migrans"

        updated_state, sent, report = self.run_notify_monitor(empty_state(), [record])

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][3], "Black Kite - Leester Marsch NW / Weyhe")
        self.assertNotIn("NEW RARE BIRDS", sent[0][0])
        self.assertIn("HB-HB", sent[0][0])
        self.assertIn("Black Kite (Milvus migrans)", sent[0][0])
        self.assertIn("1 - Leester Marsch NW [2918_4_50s] / Weyhe (NI, DH)", sent[0][0])
        self.assertIn("Black Kite (Milvus migrans)", report)
        self.assertIn("test", updated_state["monitors"])

    def test_multiple_new_records_subject_lists_species_with_duplicate_counts(self):
        from ornitho.state import empty_state

        records = [
            sample_record_with_location("Black Kite", "First Marsh"),
            sample_record_with_location("Black Kite", "Second Marsh"),
            sample_record_with_location("Osprey", "River"),
        ]

        _updated_state, sent, _report = self.run_notify_monitor(empty_state(), records)

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][3], "Black Kite (2), Osprey")

    def test_repeated_run_sends_no_second_notification(self):
        from ornitho.state import empty_state

        record = sample_record()

        updated_state, first_sent, _ = self.run_notify_monitor(empty_state(), [record])
        _, second_sent, second_report = self.run_notify_monitor(updated_state, [record])

        self.assertEqual(len(first_sent), 1)
        self.assertEqual(second_sent, [])
        self.assertIn("No new rare records.", second_report)

    def test_monitor_histories_remain_independent(self):
        from ornitho.state import empty_state, update_state

        record = sample_record()
        state = update_state(empty_state(), "other-monitor", [("HB-HB", [record])])

        _, sent, report = self.run_notify_monitor(state, [record], monitor_name="test")

        self.assertEqual(len(sent), 1)
        self.assertIn("Test Bird (Avis testus)", report)


if __name__ == "__main__":
    unittest.main()
