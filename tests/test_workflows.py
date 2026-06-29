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


if __name__ == "__main__":
    unittest.main()
