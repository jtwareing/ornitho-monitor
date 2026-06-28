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

    def test_hourly_schedule_avoids_top_of_hour(self):
        hourly = self.workflow_text("ornitho-notify.yml")

        self.assertIn('cron: "17 * * * *"', hourly)
        self.assertNotIn('cron: "0 * * * *"', hourly)

    def test_daily_workflow_still_uses_daily_mode_entrypoint(self):
        daily = self.workflow_text("ornitho.yml")

        self.assertIn("xvfb-run python -m ornitho.main", daily)
        self.assertNotIn("--mode notify", daily)


if __name__ == "__main__":
    unittest.main()
