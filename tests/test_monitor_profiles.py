import importlib
import json
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
    def test_monitors_load_from_json_config(self):
        os.environ["EMAIL_TO"] = "birds@example.test"
        os.environ.pop("SCRAPER_BACKEND", None)
        os.environ.pop("ORNITHO_NOTIFY_EXTRA_TARGETS", None)
        import config

        config = importlib.reload(config)

        self.assertEqual(len(config.MONITORS), 2)
        self.assertEqual(config.MONITORS[0].name, "default")
        self.assertTrue(config.MONITORS[0].enabled)
        self.assertEqual(config.MONITORS[0].email_to, "birds@example.test")
        self.assertEqual(config.MONITORS[0].targets, config.TARGETS)
        self.assertEqual(config.MONITORS[0].categories["daily"], ("rare",))
        self.assertEqual(config.MONITORS[0].categories["notify"], ("rare", "veryrare"))
        self.assertEqual(config.MONITORS[1].name, "Simon")
        self.assertTrue(config.MONITORS[1].enabled)
        self.assertEqual(config.MONITORS[1].email_to, "sim.kiese@gmail.com")
        self.assertEqual(
            config.MONITORS[1].targets,
            [("NI", "WTM"), ("NI", "AUR"), ("NI", "FRI"), ("BE", "B")],
        )
        self.assertEqual(config.MONITORS[1].categories["daily"], ("rare",))
        self.assertEqual(config.MONITORS[1].categories["notify"], ("rare", "veryrare"))
        self.assertEqual(config.SCRAPER_BACKEND, "playwright")
        self.assertEqual(config.NOTIFY_EXTRA_TARGETS, [])

    def test_parse_targets_requires_state_district_format(self):
        import config

        self.assertEqual(config.parse_targets("SH-NF, hb-hb"), [("SH", "NF"), ("HB", "HB")])
        with self.assertRaisesRegex(config.MonitorConfigError, "STATE-DISTRICT"):
            config.parse_targets("SH")

    def test_invalid_monitor_config_has_clear_error(self):
        import config

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir, "monitors.json")
            path.write_text(
                """
                {
                  "schema_version": 1,
                  "monitors": [
                    {
                      "name": "bad",
                      "enabled": true,
                      "categories": {"daily": ["rare"], "notify": ["rare"]},
                      "targets": ["NI-OHZ"]
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                config.MonitorConfigError,
                "exactly one of email_to or email_to_env",
            ):
                config.load_monitors(path)

    def test_duplicate_monitor_names_are_rejected(self):
        import config

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir, "monitors.json")
            path.write_text(
                """
                {
                  "schema_version": 1,
                  "monitors": [
                    {
                      "name": "same",
                      "enabled": true,
                      "email_to": "a@example.test",
                      "categories": {"daily": ["rare"], "notify": ["rare"]},
                      "targets": ["NI-OHZ"]
                    },
                    {
                      "name": "same",
                      "enabled": true,
                      "email_to": "b@example.test",
                      "categories": {"daily": ["rare"], "notify": ["rare"]},
                      "targets": ["NI-VER"]
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )

            with self.assertRaisesRegex(config.MonitorConfigError, "unique"):
                config.load_monitors(path)

    def test_missing_schema_version_is_rejected(self):
        import config

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir, "monitors.json")
            path.write_text('{"monitors": []}', encoding="utf-8")

            with self.assertRaisesRegex(config.MonitorConfigError, "schema_version"):
                config.load_monitors(path)

    def test_invalid_monitor_category_is_rejected(self):
        import config

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir, "monitors.json")
            path.write_text(
                """
                {
                  "schema_version": 1,
                  "monitors": [
                    {
                      "name": "bad",
                      "enabled": true,
                      "email_to": "bad@example.test",
                      "categories": {"daily": ["rare"], "notify": ["mega"]},
                      "targets": ["NI-OHZ"]
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )

            with self.assertRaisesRegex(config.MonitorConfigError, "unsupported category"):
                config.load_monitors(path)

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

    def test_multiple_monitors_send_separate_reports_and_keep_state_isolated(self):
        install_dependency_stubs()
        import config
        import ornitho.main as main
        from ornitho.state import empty_state

        sent = []

        def fake_check_target_with_retry(browser, state, district, attempts, wait_seconds):
            return [
                {
                    "date": "Saturday, June 27th, 2026",
                    "location": f"{state}-{district} Marsh",
                    "count": "1",
                    "species": f"{state}-{district} Bird",
                    "scientific": "Avis testus",
                    "detail": "",
                }
            ]

        def fake_send_email(report, dry_run=False, email_to=None, subject=None):
            sent.append((email_to, report))

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

                monitors = [
                    config.Monitor("default", "default@example.test", [("HB", "HB")]),
                    config.Monitor("Simon", "sim.kiese@gmail.com", [("NI", "WTM")]),
                ]
                state = empty_state()
                for monitor in monitors:
                    state = main.run_monitor(object(), monitor, state, persist_state=True)
                default_report = Path(tmpdir, "default_report.txt").read_text(encoding="utf-8")
                simon_report = Path(tmpdir, "Simon_report.txt").read_text(encoding="utf-8")
                multi_report = Path(tmpdir, "multi_report.txt").read_text(encoding="utf-8")
            finally:
                main.OUT = original_out
                main.STATE_PATH = original_state_path
                main.DRY_RUN = original_dry_run
                main.check_target_with_retry = original_check
                main.send_email = original_send

        self.assertEqual([recipient for recipient, _ in sent], ["default@example.test", "sim.kiese@gmail.com"])
        self.assertIn("HB-HB Bird", sent[0][1])
        self.assertNotIn("NI-WTM Bird", sent[0][1])
        self.assertIn("NI-WTM Bird", sent[1][1])
        self.assertNotIn("HB-HB Bird", sent[1][1])
        self.assertEqual(set(state["monitors"]), {"default", "Simon"})
        self.assertIn("HB-HB", state["monitors"]["default"]["targets"])
        self.assertIn("NI-WTM", state["monitors"]["Simon"]["targets"])

        self.assertIn("HB-HB Bird", default_report)
        self.assertIn("NI-WTM Bird", simon_report)
        self.assertIn("NI-WTM Bird", multi_report)

    def test_run_deduplicates_overlapping_direct_scrape_queries_and_fans_out(self):
        install_dependency_stubs()
        import config
        import ornitho.main as main
        from ornitho.state import load_state

        record = {
            "date": "Saturday, June 27th, 2026",
            "location": "Shared Marsh",
            "count": "1",
            "species": "Shared Bird",
            "scientific": "Avis communis",
            "detail": "",
        }
        sent = []
        scrape_calls = []

        class FakeResult:
            records = [record]

            class stats:
                request_count = 1
                pages_fetched = 1
                records_parsed = 1
                categories = ("rare", "veryrare")

        class FakeDirectScraper:
            def __init__(self, *_args, **_kwargs):
                return None

            def fetch_text(self, _url):
                return "<html></html>"

            def check_target(self, target, index_html=None, categories=()):
                scrape_calls.append((target, tuple(categories)))
                return FakeResult()

        def fake_send_email(report, dry_run=False, email_to=None, subject=None):
            sent.append((email_to, report, subject))

        with tempfile.TemporaryDirectory() as tmpdir:
            original_out = main.OUT
            original_state_path = main.STATE_PATH
            original_dry_run = main.DRY_RUN
            original_backend = main.SCRAPER_BACKEND
            original_monitors = main.MONITORS
            original_direct_scraper = main.DirectOrnithoScraper
            original_send = main.send_email
            try:
                state_path = Path(tmpdir, "state.json")
                main.OUT = Path(tmpdir)
                main.STATE_PATH = state_path
                main.DRY_RUN = False
                main.SCRAPER_BACKEND = main.DIRECT_BACKEND
                main.MONITORS = [
                    config.Monitor(
                        "default",
                        "default@example.test",
                        [("HB", "HB")],
                        categories={"daily": ("rare",), "notify": ("rare", "veryrare")},
                    ),
                    config.Monitor(
                        "Simon",
                        "simon@example.test",
                        [("HB", "HB")],
                        categories={"daily": ("rare",), "notify": ("rare", "veryrare")},
                    ),
                ]
                main.DirectOrnithoScraper = FakeDirectScraper
                main.send_email = fake_send_email

                main.run(mode=main.NOTIFY_MODE)
                saved_state = load_state(state_path)
                default_report = Path(tmpdir, "default_report.txt").read_text(encoding="utf-8")
                simon_report = Path(tmpdir, "Simon_report.txt").read_text(encoding="utf-8")
            finally:
                main.OUT = original_out
                main.STATE_PATH = original_state_path
                main.DRY_RUN = original_dry_run
                main.SCRAPER_BACKEND = original_backend
                main.MONITORS = original_monitors
                main.DirectOrnithoScraper = original_direct_scraper
                main.send_email = original_send

        self.assertEqual(scrape_calls, [(("HB", "HB"), ("rare", "veryrare"))])
        self.assertEqual(
            [recipient for recipient, _report, _subject in sent],
            ["default@example.test", "simon@example.test"],
        )
        self.assertIn("Shared Bird", default_report)
        self.assertIn("Shared Bird", simon_report)
        self.assertEqual(set(saved_state["monitors"]), {"default", "Simon"})
        self.assertIn("HB-HB", saved_state["monitors"]["default"]["targets"])
        self.assertIn("HB-HB", saved_state["monitors"]["Simon"]["targets"])

    def test_per_monitor_categories_create_distinct_scrape_queries(self):
        install_dependency_stubs()
        import config
        import ornitho.main as main

        scrape_calls = []

        class FakeResult:
            records = []

            class stats:
                request_count = 1
                pages_fetched = 1
                records_parsed = 0
                categories = ("rare",)

        class FakeDirectScraper:
            def __init__(self, *_args, **_kwargs):
                return None

            def fetch_text(self, _url):
                return "<html></html>"

            def check_target(self, target, index_html=None, categories=()):
                scrape_calls.append((target, tuple(categories)))
                return FakeResult()

        def fake_send_email(*_args, **_kwargs):
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            original_out = main.OUT
            original_state_path = main.STATE_PATH
            original_dry_run = main.DRY_RUN
            original_backend = main.SCRAPER_BACKEND
            original_monitors = main.MONITORS
            original_direct_scraper = main.DirectOrnithoScraper
            original_send = main.send_email
            try:
                main.OUT = Path(tmpdir)
                main.STATE_PATH = Path(tmpdir, "state.json")
                main.DRY_RUN = True
                main.SCRAPER_BACKEND = main.DIRECT_BACKEND
                main.MONITORS = [
                    config.Monitor(
                        "rare-only",
                        "rare@example.test",
                        [("HB", "HB")],
                        categories={"daily": ("rare",), "notify": ("rare",)},
                    ),
                    config.Monitor(
                        "rare-veryrare",
                        "both@example.test",
                        [("HB", "HB")],
                        categories={"daily": ("rare",), "notify": ("rare", "veryrare")},
                    ),
                ]
                main.DirectOrnithoScraper = FakeDirectScraper
                main.send_email = fake_send_email

                main.run(mode=main.NOTIFY_MODE)
            finally:
                main.OUT = original_out
                main.STATE_PATH = original_state_path
                main.DRY_RUN = original_dry_run
                main.SCRAPER_BACKEND = original_backend
                main.MONITORS = original_monitors
                main.DirectOrnithoScraper = original_direct_scraper
                main.send_email = original_send

        self.assertEqual(
            scrape_calls,
            [
                (("HB", "HB"), ("rare",)),
                (("HB", "HB"), ("rare", "veryrare")),
            ],
        )

    def test_successful_run_writes_run_summary(self):
        install_dependency_stubs()
        import config
        import ornitho.main as main

        record = {
            "date": "Saturday, June 27th, 2026",
            "location": "Summary Marsh",
            "count": "1",
            "species": "Summary Bird",
            "scientific": "Avis summa",
            "detail": "",
        }

        class FakeResult:
            records = [record]

            class stats:
                request_count = 1
                pages_fetched = 1
                records_parsed = 1
                categories = ("rare",)

        class FakeDirectScraper:
            def __init__(self, *_args, **_kwargs):
                return None

            def fetch_text(self, _url):
                return "<html></html>"

            def check_target(self, target, index_html=None, categories=()):
                return FakeResult()

        def fake_send_email(*_args, **_kwargs):
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            original_out = main.OUT
            original_state_path = main.STATE_PATH
            original_dry_run = main.DRY_RUN
            original_backend = main.SCRAPER_BACKEND
            original_monitors = main.MONITORS
            original_direct_scraper = main.DirectOrnithoScraper
            original_send = main.send_email
            try:
                main.OUT = Path(tmpdir)
                main.STATE_PATH = Path(tmpdir, "state.json")
                main.DRY_RUN = True
                main.SCRAPER_BACKEND = main.DIRECT_BACKEND
                main.MONITORS = [
                    config.Monitor(
                        "summary",
                        "summary@example.test",
                        [("HB", "HB")],
                        categories={"daily": ("rare",), "notify": ("rare",)},
                    )
                ]
                main.DirectOrnithoScraper = FakeDirectScraper
                main.send_email = fake_send_email

                main.run(mode=main.NOTIFY_MODE)
                summary = json.loads(Path(tmpdir, "run_summary.json").read_text(encoding="utf-8"))
            finally:
                main.OUT = original_out
                main.STATE_PATH = original_state_path
                main.DRY_RUN = original_dry_run
                main.SCRAPER_BACKEND = original_backend
                main.MONITORS = original_monitors
                main.DirectOrnithoScraper = original_direct_scraper
                main.send_email = original_send

        self.assertEqual(summary["overall_run_status"], "SUCCESS")
        self.assertEqual(summary["backend"], main.DIRECT_BACKEND)
        self.assertTrue(summary["dry_run"])
        self.assertEqual(summary["monitors_loaded"], 1)
        self.assertEqual(summary["monitors_enabled"], 1)
        self.assertEqual(summary["unique_scrape_queries_planned"], 1)
        self.assertEqual(summary["actual_scrape_queries_executed"], 1)
        self.assertEqual(summary["records_per_monitor"]["summary"]["current_records"], 1)
        self.assertEqual(summary["records_per_monitor"]["summary"]["new_records"], 1)
        self.assertEqual(summary["emails"]["user_sent"], [])
        self.assertEqual(summary["emails"]["user_skipped"][0]["reason"], "DRY_RUN enabled")
        self.assertFalse(summary["state"]["saved"])
        self.assertEqual(summary["state"]["skipped_reason"], "DRY_RUN enabled")

    def test_bounded_direct_failure_writes_summary_and_operations_alert_only(self):
        install_dependency_stubs()
        import config
        import ornitho.main as main

        sent = []

        class FailingDirectScraper:
            def __init__(self, *_args, **_kwargs):
                return None

            def fetch_text(self, _url):
                raise TimeoutError("direct setup timed out")

        def fail_check_target_with_retry(*_args, **_kwargs):
            raise AssertionError("Playwright retry path should not be used")

        def fake_send_email(report, dry_run=False, email_to=None, subject=None):
            sent.append((report, dry_run, email_to, subject))

        with tempfile.TemporaryDirectory() as tmpdir:
            original_out = main.OUT
            original_state_path = main.STATE_PATH
            original_dry_run = main.DRY_RUN
            original_backend = main.SCRAPER_BACKEND
            original_monitors = main.MONITORS
            original_direct_scraper = main.DirectOrnithoScraper
            original_check = main.check_target_with_retry
            original_send = main.send_email
            original_operations_email = main.OPERATIONS_EMAIL
            original_setup_attempts = main.DIRECT_SETUP_ATTEMPTS
            original_backoff = main.DIRECT_RETRY_BACKOFF_SECONDS
            original_total_timeout = main.DIRECT_TOTAL_TIMEOUT_SECONDS
            try:
                main.OUT = Path(tmpdir)
                main.STATE_PATH = Path(tmpdir, "state.json")
                main.DRY_RUN = False
                main.SCRAPER_BACKEND = main.DIRECT_WITH_RETRIES_BACKEND
                main.MONITORS = [config.Monitor("test", "user@example.test", [("HB", "HB")])]
                main.DirectOrnithoScraper = FailingDirectScraper
                main.check_target_with_retry = fail_check_target_with_retry
                main.send_email = fake_send_email
                main.OPERATIONS_EMAIL = "ops@example.test"
                main.DIRECT_SETUP_ATTEMPTS = 1
                main.DIRECT_RETRY_BACKOFF_SECONDS = 1
                main.DIRECT_TOTAL_TIMEOUT_SECONDS = 5

                with self.assertRaisesRegex(main.DirectScraperRuntimeError, "Direct HTTP setup failed"):
                    main.run(mode=main.NOTIFY_MODE)

                summary = json.loads(Path(tmpdir, "run_summary.json").read_text(encoding="utf-8"))
                failure = Path(tmpdir, "scrape_failure.txt").read_text(encoding="utf-8")
            finally:
                main.OUT = original_out
                main.STATE_PATH = original_state_path
                main.DRY_RUN = original_dry_run
                main.SCRAPER_BACKEND = original_backend
                main.MONITORS = original_monitors
                main.DirectOrnithoScraper = original_direct_scraper
                main.check_target_with_retry = original_check
                main.send_email = original_send
                main.OPERATIONS_EMAIL = original_operations_email
                main.DIRECT_SETUP_ATTEMPTS = original_setup_attempts
                main.DIRECT_RETRY_BACKOFF_SECONDS = original_backoff
                main.DIRECT_TOTAL_TIMEOUT_SECONDS = original_total_timeout

        self.assertIn("no email sent and state not updated", failure)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][2], "ops@example.test")
        self.assertEqual(sent[0][3], main.OPERATIONS_ALERT_SUBJECT)
        self.assertIn("No user bird-notification emails", sent[0][0])
        self.assertEqual(summary["overall_run_status"], "FAILED")
        self.assertEqual(summary["unique_scrape_queries_planned"], 1)
        self.assertEqual(summary["actual_scrape_queries_executed"], 0)
        self.assertEqual(len(summary["scrape_setup_attempts"]), 1)
        self.assertFalse(summary["direct_http"]["success"])
        self.assertEqual(summary["emails"]["user_sent"], [])
        self.assertTrue(summary["emails"]["operations_alert_sent"])
        self.assertFalse(summary["state"]["saved"])
        self.assertEqual(summary["state"]["skipped_reason"], "run failed")
        self.assertFalse(Path(tmpdir, "state.json").exists())

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

    def test_run_monitor_passes_monitor_mode_categories_to_direct_scraper(self):
        install_dependency_stubs()
        import config
        import ornitho.main as main
        from ornitho.state import empty_state

        categories_seen = []

        class FakeResult:
            records = []

            class stats:
                request_count = 1
                pages_fetched = 1
                records_parsed = 0
                categories = ("rare", "veryrare")

        class FakeDirectScraper:
            def check_target(self, target, index_html=None, categories=()):
                categories_seen.append(tuple(categories))
                return FakeResult()

        def fake_send_email(report, dry_run=False, email_to=None, subject=None):
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            original_out = main.OUT
            original_dry_run = main.DRY_RUN
            original_send = main.send_email
            try:
                main.OUT = Path(tmpdir)
                main.DRY_RUN = True
                main.send_email = fake_send_email

                monitor = config.Monitor(
                    name="test",
                    email_to="profile@example.test",
                    targets=[("HB", "HB")],
                    categories={"daily": ("rare",), "notify": ("rare", "veryrare")},
                )
                main.run_monitor(
                    None,
                    monitor,
                    empty_state(),
                    mode=main.NOTIFY_MODE,
                    persist_state=False,
                    backend=main.DIRECT_BACKEND,
                    direct_scraper=FakeDirectScraper(),
                    direct_index_html="<html></html>",
                )
            finally:
                main.OUT = original_out
                main.DRY_RUN = original_dry_run
                main.send_email = original_send

        self.assertEqual(categories_seen, [("rare", "veryrare")])

    def test_disabled_monitors_are_skipped_before_scraping_or_email(self):
        install_dependency_stubs()
        import config
        import ornitho.main as main

        class FakeBrowser:
            def close(self):
                return None

        class FakeChromium:
            def launch(self, headless=False):
                return FakeBrowser()

        class FakePlaywright:
            chromium = FakeChromium()

        class FakePlaywrightContext:
            def __enter__(self):
                return FakePlaywright()

            def __exit__(self, exc_type, exc, tb):
                return False

        def fail_check_target_with_retry(*_args, **_kwargs):
            raise AssertionError("disabled monitor should not scrape")

        def fail_send_email(*_args, **_kwargs):
            raise AssertionError("disabled monitor should not email")

        with tempfile.TemporaryDirectory() as tmpdir:
            original_out = main.OUT
            original_state_path = main.STATE_PATH
            original_dry_run = main.DRY_RUN
            original_backend = main.SCRAPER_BACKEND
            original_monitors = main.MONITORS
            original_sync_playwright = main.sync_playwright
            original_check = main.check_target_with_retry
            original_send = main.send_email
            try:
                main.OUT = Path(tmpdir)
                main.STATE_PATH = Path(tmpdir, "state.json")
                main.DRY_RUN = True
                main.SCRAPER_BACKEND = main.PLAYWRIGHT_BACKEND
                main.MONITORS = [
                    config.Monitor(
                        "disabled",
                        "disabled@example.test",
                        [("HB", "HB")],
                        enabled=False,
                    )
                ]
                main.sync_playwright = lambda: FakePlaywrightContext()
                main.check_target_with_retry = fail_check_target_with_retry
                main.send_email = fail_send_email

                main.run(mode=main.NOTIFY_MODE)
            finally:
                main.OUT = original_out
                main.STATE_PATH = original_state_path
                main.DRY_RUN = original_dry_run
                main.SCRAPER_BACKEND = original_backend
                main.MONITORS = original_monitors
                main.sync_playwright = original_sync_playwright
                main.check_target_with_retry = original_check
                main.send_email = original_send

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

    def test_direct_with_retries_does_not_use_playwright_when_direct_fails(self):
        install_dependency_stubs()
        import ornitho.main as main

        class FailingDirectScraper:
            def check_target(self, *_args, **_kwargs):
                raise RuntimeError("direct unavailable")

        def fail_check_target_with_retry(*_args, **_kwargs):
            raise AssertionError("Playwright retry path should not be used")

        with tempfile.TemporaryDirectory() as tmpdir:
            original_out = main.OUT
            original_check = main.check_target_with_retry
            try:
                main.OUT = Path(tmpdir)
                main.check_target_with_retry = fail_check_target_with_retry

                with self.assertRaisesRegex(RuntimeError, "direct unavailable"):
                    main.check_target_records(
                        None,
                        FailingDirectScraper(),
                        "<html></html>",
                        "HB",
                        "HB",
                        backend=main.DIRECT_WITH_RETRIES_BACKEND,
                    )

                failure_artifact = Path(tmpdir, "scrape_failure.txt").read_text(
                    encoding="utf-8"
                )
            finally:
                main.OUT = original_out
                main.check_target_with_retry = original_check

        self.assertIn("Direct HTTP failed for HB-HB", failure_artifact)
        self.assertIn("no email sent and state not updated", failure_artifact)

    def test_direct_with_fallback_handles_initial_direct_setup_failure(self):
        install_dependency_stubs()
        import config
        import ornitho.main as main

        seen_targets = []

        class FailingDirectScraper:
            def __init__(self, *_args, **_kwargs):
                return None

            def fetch_text(self, _url):
                raise TimeoutError("direct setup timed out")

        class FakeBrowser:
            def close(self):
                return None

        class FakeChromium:
            def launch(self, headless=False):
                return FakeBrowser()

        class FakePlaywright:
            chromium = FakeChromium()

        class FakePlaywrightContext:
            def __enter__(self):
                return FakePlaywright()

            def __exit__(self, exc_type, exc, tb):
                return False

        def fake_check_target_with_retry(browser, state, district, attempts, wait_seconds):
            seen_targets.append((state, district))
            return []

        def fake_send_email(report, dry_run=False, email_to=None, subject=None):
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            original_out = main.OUT
            original_state_path = main.STATE_PATH
            original_dry_run = main.DRY_RUN
            original_backend = main.SCRAPER_BACKEND
            original_monitors = main.MONITORS
            original_direct_scraper = main.DirectOrnithoScraper
            original_sync_playwright = main.sync_playwright
            original_check = main.check_target_with_retry
            original_send = main.send_email
            try:
                main.OUT = Path(tmpdir)
                main.STATE_PATH = Path(tmpdir, "state.json")
                main.DRY_RUN = True
                main.SCRAPER_BACKEND = main.DIRECT_WITH_FALLBACK_BACKEND
                main.MONITORS = [config.Monitor("test", "profile@example.test", [("HB", "HB")])]
                main.DirectOrnithoScraper = FailingDirectScraper
                main.sync_playwright = lambda: FakePlaywrightContext()
                main.check_target_with_retry = fake_check_target_with_retry
                main.send_email = fake_send_email

                main.run(mode=main.NOTIFY_MODE)
            finally:
                main.OUT = original_out
                main.STATE_PATH = original_state_path
                main.DRY_RUN = original_dry_run
                main.SCRAPER_BACKEND = original_backend
                main.MONITORS = original_monitors
                main.DirectOrnithoScraper = original_direct_scraper
                main.sync_playwright = original_sync_playwright
                main.check_target_with_retry = original_check
                main.send_email = original_send

        self.assertEqual(seen_targets, [("HB", "HB")])

    def test_direct_with_retries_setup_failure_stops_before_email_or_state(self):
        install_dependency_stubs()
        import config
        import ornitho.main as main

        class FailingDirectScraper:
            def __init__(self, *_args, **_kwargs):
                return None

            def fetch_text(self, _url):
                raise TimeoutError("direct setup timed out")

        def fail_sync_playwright():
            raise AssertionError("Playwright should not be launched")

        def fail_check_target_with_retry(*_args, **_kwargs):
            raise AssertionError("Playwright retry path should not be used")

        def fail_send_email(*_args, **_kwargs):
            raise AssertionError("email should not be sent after direct setup failure")

        with tempfile.TemporaryDirectory() as tmpdir:
            original_out = main.OUT
            original_state_path = main.STATE_PATH
            original_dry_run = main.DRY_RUN
            original_backend = main.SCRAPER_BACKEND
            original_monitors = main.MONITORS
            original_direct_scraper = main.DirectOrnithoScraper
            original_sync_playwright = main.sync_playwright
            original_check = main.check_target_with_retry
            original_send = main.send_email
            original_setup_attempts = main.DIRECT_SETUP_ATTEMPTS
            original_backoff = main.DIRECT_RETRY_BACKOFF_SECONDS
            original_total_timeout = main.DIRECT_TOTAL_TIMEOUT_SECONDS
            try:
                main.OUT = Path(tmpdir)
                main.STATE_PATH = Path(tmpdir, "state.json")
                main.DRY_RUN = False
                main.SCRAPER_BACKEND = main.DIRECT_WITH_RETRIES_BACKEND
                main.MONITORS = [config.Monitor("test", "profile@example.test", [("HB", "HB")])]
                main.DirectOrnithoScraper = FailingDirectScraper
                main.sync_playwright = fail_sync_playwright
                main.check_target_with_retry = fail_check_target_with_retry
                main.send_email = fail_send_email
                main.DIRECT_SETUP_ATTEMPTS = 1
                main.DIRECT_RETRY_BACKOFF_SECONDS = 1
                main.DIRECT_TOTAL_TIMEOUT_SECONDS = 5

                with self.assertRaisesRegex(
                    main.DirectScraperRuntimeError,
                    "Direct HTTP setup failed",
                ):
                    main.run(mode=main.NOTIFY_MODE)

                failure_artifact = Path(tmpdir, "scrape_failure.txt").read_text(
                    encoding="utf-8"
                )
            finally:
                main.OUT = original_out
                main.STATE_PATH = original_state_path
                main.DRY_RUN = original_dry_run
                main.SCRAPER_BACKEND = original_backend
                main.MONITORS = original_monitors
                main.DirectOrnithoScraper = original_direct_scraper
                main.sync_playwright = original_sync_playwright
                main.check_target_with_retry = original_check
                main.send_email = original_send
                main.DIRECT_SETUP_ATTEMPTS = original_setup_attempts
                main.DIRECT_RETRY_BACKOFF_SECONDS = original_backoff
                main.DIRECT_TOTAL_TIMEOUT_SECONDS = original_total_timeout

        self.assertIn("no email sent and state not updated", failure_artifact)
        self.assertFalse(Path(tmpdir, "state.json").exists())

    def test_explicit_none_recipient_does_not_fall_back_to_global_email_to(self):
        os.environ["EMAIL_FROM"] = "from@example.test"
        os.environ["EMAIL_TO"] = "global@example.test"
        os.environ["EMAIL_PASSWORD"] = "password"

        from emailer import send_email

        with self.assertRaisesRegex(RuntimeError, "EMAIL_TO"):
            send_email("report", email_to=None)


if __name__ == "__main__":
    unittest.main()
