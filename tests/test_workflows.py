from pathlib import Path
import unittest


class WorkflowTests(unittest.TestCase):
    def workflow_text(self, name):
        return Path(".github/workflows", name).read_text(encoding="utf-8")

    def test_daily_and_hourly_share_state_concurrency(self):
        daily = self.workflow_text("ornitho.yml")
        hourly = self.workflow_text("ornitho-notify.yml")

        self.assertIn("group: ornitho-monitor-state", daily)
        self.assertIn("group: ornitho-monitor-state", hourly)
        self.assertIn("cancel-in-progress: false", daily)
        self.assertIn("cancel-in-progress: false", hourly)

    def test_hourly_commits_state_only_after_successful_non_dry_run(self):
        hourly = self.workflow_text("ornitho-notify.yml")

        self.assertIn("Commit updated state", hourly)
        self.assertIn("success()", hourly)
        self.assertIn("inputs.dry_run == false", hourly)
        self.assertIn("git diff --quiet -- state/state.json", hourly)
        self.assertIn("git push", hourly)

    def test_hourly_notifications_are_dispatch_only(self):
        hourly = self.workflow_text("ornitho-notify.yml")

        self.assertIn("workflow_dispatch:", hourly)
        self.assertNotIn("schedule:", hourly)
        self.assertNotIn("cron:", hourly)

    def test_daily_schedule_runs_around_berlin_8pm_off_top_of_hour(self):
        daily = self.workflow_text("ornitho.yml")

        self.assertIn('cron: "23 18 * * *"', daily)
        self.assertIn('cron: "23 19 * * *"', daily)
        self.assertNotIn('cron: "0 18 * * *"', daily)
        self.assertNotIn('cron: "0 19 * * *"', daily)
        self.assertIn('if [ "${berlin_hour}" = "20" ]; then', daily)

    def test_daily_workflow_still_uses_daily_mode_entrypoint(self):
        daily = self.workflow_text("ornitho.yml")

        self.assertIn("xvfb-run python -m ornitho.main", daily)
        self.assertNotIn("--mode notify", daily)

    def test_production_workflows_default_to_playwright_backend(self):
        daily = self.workflow_text("ornitho.yml")

        self.assertIn("SCRAPER_BACKEND: ${{ vars.SCRAPER_BACKEND || 'playwright' }}", daily)
        self.assertNotIn("ORNITHO_CATEGORIES:", daily)
        self.assertIn('echo "scraper_backend=${SCRAPER_BACKEND}"', daily)

    def test_hourly_workflow_uses_bounded_direct_backend_without_observer_target(self):
        hourly = self.workflow_text("ornitho-notify.yml")
        daily = self.workflow_text("ornitho.yml")

        self.assertIn("SCRAPER_BACKEND: direct_with_retries", hourly)
        self.assertIn("OPERATIONS_EMAIL: ${{ secrets.OPERATIONS_EMAIL }}", hourly)
        self.assertIn("OPERATIONS_EMAIL configured", hourly)
        self.assertIn('DIRECT_HTTP_TIMEOUT_SECONDS: "30"', hourly)
        self.assertIn('DIRECT_SETUP_ATTEMPTS: "2"', hourly)
        self.assertIn('DIRECT_RETRY_BACKOFF_SECONDS: "5"', hourly)
        self.assertIn('DIRECT_TOTAL_TIMEOUT_SECONDS: "240"', hourly)
        self.assertIn("timeout-minutes: 8", hourly)
        self.assertNotIn("python -m playwright install", hourly)
        self.assertIn("python -m ornitho.main --mode notify", hourly)
        self.assertNotIn("xvfb-run python -m ornitho.main --mode notify", hourly)
        self.assertNotIn("ORNITHO_CATEGORIES:", hourly)
        self.assertNotIn("ORNITHO_NOTIFY_EXTRA_TARGETS", hourly)
        self.assertNotIn("SH-NF", hourly)
        self.assertNotIn("ORNITHO_NOTIFY_EXTRA_TARGETS", daily)

    def test_direct_shadow_compare_is_manual_only_and_no_email_or_state(self):
        shadow = self.workflow_text("ornitho-direct-shadow-compare.yml")

        self.assertIn("workflow_dispatch:", shadow)
        self.assertIn("extra_targets:", shadow)
        self.assertIn("--extra-targets", shadow)
        self.assertNotIn("schedule:", shadow)
        self.assertNotIn("cron:", shadow)
        self.assertIn("permissions:", shadow)
        self.assertIn("contents: read", shadow)
        self.assertIn("xvfb-run python -m ornitho.direct_shadow_run", shadow)
        self.assertIn("output/*_last_page.html", shadow)
        self.assertIn("output/*_last_page_text.txt", shadow)
        self.assertNotIn("ornitho.main", shadow)
        self.assertNotIn("EMAIL_PASSWORD", shadow)
        self.assertNotIn("git push", shadow)
        self.assertNotIn("state/state.json", shadow)


if __name__ == "__main__":
    unittest.main()
