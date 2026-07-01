import importlib
import os
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
    else:
        sync_api = sys.modules["playwright.sync_api"]
        if not hasattr(sync_api, "sync_playwright"):
            sync_api.sync_playwright = lambda: None


class MonitorProfileTests(unittest.TestCase):
    def test_default_monitor_uses_email_to_and_current_targets(self):
        original_extra_targets = os.environ.get("ORNITHO_NOTIFY_EXTRA_TARGETS")
        os.environ["EMAIL_TO"] = "birds@example.test"
        os.environ.pop("SCRAPER_BACKEND", None)
        os.environ["ORNITHO_NOTIFY_EXTRA_TARGETS"] = "SH-NF"
        import config

        try:
            config = importlib.reload(config)

            self.assertEqual(len(config.MONITORS), 1)
            self.assertEqual(config.MONITORS[0].name, "default")
            self.assertEqual(config.MONITORS[0].email_to, "birds@example.test")
            self.assertEqual(config.MONITORS[0].targets, config.TARGETS)
            self.assertEqual(config.SCRAPER_BACKEND, "playwright")
            self.assertEqual(config.NOTIFY_EXTRA_TARGETS, [("SH", "NF")])
        finally:
            if original_extra_targets is None:
                os.environ.pop("ORNITHO_NOTIFY_EXTRA_TARGETS", None)
            else:
                os.environ["ORNITHO_NOTIFY_EXTRA_TARGETS"] = original_extra_targets
            importlib.reload(config)

    def test_parse_targets_requires_state_district_format(self):
        import config

        self.assertEqual(config.parse_targets("SH-NF, hb-hb"), [("SH", "NF"), ("HB", "HB")])
        with self.assertRaisesRegex(ValueError, "STATE-DISTRICT"):
            config.parse_targets("SH")

    def test_run_monitor_uses_monitor_targets_and_recipient(self):
        install_dependency_stubs()
        import config
        import ornitho.main as main
        from ornitho.state import empty_state

        seen_targets = []
        sent = []

        def fake_check_target_with_retry(browser, state, district, attempts, wait_seconds):
            seen_targets.append((state, district))
            return []

        def fake_send_email(report, dry_run=False, email_to=None, subject=None):
            sent.append((report, dry_run, email_to))

        with tempfile.TemporaryDirectory() as tmpdir:
            original_out = main.OUT
            original_dry_run = main.DRY_RUN
            original_check = main.check_target_with_retry
            original_send = main.send_email
            try:
                main.OUT = Path(tmpdir)
                main.DRY_RUN = True
                main.check_target_with_retry = fake_check_target_with_retry
                main.send_email = fake_send_email

                monitor = config.Monitor(
                    name="test",
                    email_to="profile@example.test",
                    targets=[("HB", "HB")],
                )
                main.run_monitor(object(), monitor, empty_state(), persist_state=False)

                report = Path(tmpdir, "multi_report.txt").read_text(encoding="utf-8")
            finally:
                main.OUT = original_out
                main.DRY_RUN = original_dry_run
                main.check_target_with_retry = original_check
                main.send_email = original_send

        self.assertEqual(seen_targets, [("HB", "HB")])
        self.assertIn("[HB-HB]", report)
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0][1])
        self.assertEqual(sent[0][2], "profile@example.test")

    def test_run_monitor_can_include_notify_only_extra_targets(self):
        install_dependency_stubs()
        import config
        import ornitho.main as main
        from ornitho.state import empty_state

        seen_targets = []

        def fake_check_target_with_retry(browser, state, district, attempts, wait_seconds):
            seen_targets.append((state, district))
            return []

        def fake_send_email(report, dry_run=False, email_to=None, subject=None):
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            original_out = main.OUT
            original_dry_run = main.DRY_RUN
            original_check = main.check_target_with_retry
            original_send = main.send_email
            try:
                main.OUT = Path(tmpdir)
                main.DRY_RUN = True
                main.check_target_with_retry = fake_check_target_with_retry
                main.send_email = fake_send_email

                monitor = config.Monitor(
                    name="test",
                    email_to="profile@example.test",
                    targets=[("HB", "HB")],
                )
                main.run_monitor(
                    object(),
                    monitor,
                    empty_state(),
                    persist_state=False,
                    extra_targets=[("SH", "NF")],
                )
            finally:
                main.OUT = original_out
                main.DRY_RUN = original_dry_run
                main.check_target_with_retry = original_check
                main.send_email = original_send

        self.assertEqual(seen_targets, [("HB", "HB"), ("SH", "NF")])

    def test_run_monitor_saves_state_when_persistence_is_enabled(self):
        install_dependency_stubs()
        import config
        import ornitho.main as main
        from ornitho.state import empty_state, load_state

        record = {
            "date": "Saturday, June 27th, 2026",
            "location": "Test Marsh",
            "count": "1",
            "species": "Test Bird",
            "scientific": "Avis testus",
            "detail": "",
        }

        def fake_check_target_with_retry(browser, state, district, attempts, wait_seconds):
            return [record]

        def fake_send_email(report, dry_run=False, email_to=None, subject=None):
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            original_out = main.OUT
            original_state_path = main.STATE_PATH
            original_dry_run = main.DRY_RUN
            original_check = main.check_target_with_retry
            original_send = main.send_email
            try:
                state_path = Path(tmpdir, "state.json")
                main.OUT = Path(tmpdir)
                main.STATE_PATH = state_path
                main.DRY_RUN = True
                main.check_target_with_retry = fake_check_target_with_retry
                main.send_email = fake_send_email

                monitor = config.Monitor(
                    name="test",
                    email_to="profile@example.test",
                    targets=[("HB", "HB")],
                )
                main.run_monitor(object(), monitor, empty_state(), persist_state=True)
                saved_state = load_state(state_path)
            finally:
                main.OUT = original_out
                main.STATE_PATH = original_state_path
                main.DRY_RUN = original_dry_run
                main.check_target_with_retry = original_check
                main.send_email = original_send

        self.assertEqual(
            len(saved_state["monitors"]["test"]["targets"]["HB-HB"]["seen_record_keys"]),
            1,
        )

    def test_direct_backend_uses_direct_scraper_without_playwright_retry(self):
        install_dependency_stubs()
        import ornitho.main as main

        records = [{"species": "Direct Bird"}]

        class FakeResult:
            class stats:
                request_count = 1
                pages_fetched = 1
                records_parsed = 1
                categories = ("rare",)

            def __init__(self):
                self.records = records

        class FakeDirectScraper:
            def __init__(self):
                self.calls = []

            def check_target(self, target, index_html=None, categories=()):
                self.calls.append((target, index_html, categories))
                return FakeResult()

        def fail_check_target_with_retry(*_args, **_kwargs):
            raise AssertionError("Playwright retry path should not be used")

        original_check = main.check_target_with_retry
        try:
            main.check_target_with_retry = fail_check_target_with_retry
            scraper = FakeDirectScraper()
            result = main.check_target_records(
                None,
                scraper,
                "<html></html>",
                "HB",
                "HB",
                backend=main.DIRECT_BACKEND,
            )
        finally:
            main.check_target_with_retry = original_check

        self.assertEqual(result, records)
        self.assertEqual(scraper.calls[0][0], ("HB", "HB"))

    def test_direct_with_fallback_uses_playwright_when_direct_fails(self):
        install_dependency_stubs()
        import ornitho.main as main

        fallback_records = [{"species": "Fallback Bird"}]

        class FailingDirectScraper:
            def check_target(self, *_args, **_kwargs):
                raise RuntimeError("direct unavailable")

        def fake_check_target_with_retry(browser, state, district, attempts, wait_seconds):
            self.assertEqual((state, district), ("HB", "HB"))
            return fallback_records

        original_check = main.check_target_with_retry
        try:
            main.check_target_with_retry = fake_check_target_with_retry
            result = main.check_target_records(
                object(),
                FailingDirectScraper(),
                "<html></html>",
                "HB",
                "HB",
                backend=main.DIRECT_WITH_FALLBACK_BACKEND,
            )
        finally:
            main.check_target_with_retry = original_check

        self.assertEqual(result, fallback_records)

    def test_explicit_none_recipient_does_not_fall_back_to_global_email_to(self):
        os.environ["EMAIL_FROM"] = "from@example.test"
        os.environ["EMAIL_TO"] = "global@example.test"
        os.environ["EMAIL_PASSWORD"] = "password"

        from emailer import send_email

        with self.assertRaisesRegex(RuntimeError, "EMAIL_TO"):
            send_email("report", email_to=None)


if __name__ == "__main__":
    unittest.main()
