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
        os.environ["EMAIL_TO"] = "birds@example.test"
        import config

        config = importlib.reload(config)

        self.assertEqual(len(config.MONITORS), 1)
        self.assertEqual(config.MONITORS[0].name, "default")
        self.assertEqual(config.MONITORS[0].email_to, "birds@example.test")
        self.assertEqual(config.MONITORS[0].targets, config.TARGETS)

    def test_run_monitor_uses_monitor_targets_and_recipient(self):
        install_dependency_stubs()
        import config
        import ornitho.main as main

        seen_targets = []
        sent = []

        def fake_check_target_with_retry(browser, state, district, attempts, wait_seconds):
            seen_targets.append((state, district))
            return []

        def fake_send_email(report, dry_run=False, email_to=None):
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
                main.run_monitor(object(), monitor)

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

    def test_explicit_none_recipient_does_not_fall_back_to_global_email_to(self):
        os.environ["EMAIL_FROM"] = "from@example.test"
        os.environ["EMAIL_TO"] = "global@example.test"
        os.environ["EMAIL_PASSWORD"] = "password"

        from emailer import send_email

        with self.assertRaisesRegex(RuntimeError, "EMAIL_TO"):
            send_email("report", email_to=None)


if __name__ == "__main__":
    unittest.main()
