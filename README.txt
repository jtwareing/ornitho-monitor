Ornitho Daily Rare Bird Monitor

Overview
This project monitors selected Ornitho regions with Playwright, extracts rare-bird records, sends email reports, and stores persistent record state in the repository.

The scraper is deliberately separate from reporting, email, and state handling:
- ornitho/scraper.py navigates Ornitho and returns parsed records.
- ornitho/parser.py converts page text into record dictionaries.
- ornitho/direct_scraper.py can read Ornitho's JSON observation endpoint directly.
- ornitho/report.py builds plain-text daily and notification reports.
- ornitho/state.py loads, compares, updates, and saves persistent state.
- emailer.py sends or dry-runs email.
- ornitho/main.py coordinates monitor execution modes.

Monitors
A monitor is configured in monitors.json with:
- name
- email_to or email_to_env
- targets

The default monitor uses EMAIL_TO from the environment and these targets:
- NI-OHZ
- NI-VER
- NI-OL
- NI-OL*
- NI-DH
- HB-HB

Adding monitors
Add another monitor object to monitors.json with a unique name, recipient, and target list.

Example:
{
  "name": "bremen",
  "email_to": "recipient@example.com",
  "targets": ["HB-HB"]
}

Each monitor has independent state history, so the same record can be new for one monitor and already seen for another.

Adding regions
Add a tuple to a monitor's targets:
("STATE", "DISTRICT")

For example:
("HB", "HB")

Daily Summary mode
Daily Summary is the default mode:
python -m ornitho.main

It sends one report containing all current rare records. The report format is unchanged from the original daily report.

Notification mode
Notification mode is for hourly alerts:
python -m ornitho.main --mode notify

It compares current records with state/state.json.

If new records exist:
- report contains only new records
- email is sent
- state is updated after the email step

If no new records exist:
- no email is sent
- the log explains why
- state is still saved on real runs

Dry-run behavior
Set DRY_RUN=True to test safely.

Dry-run:
- scrapes Ornitho
- compares against state
- prints the email subject and body
- does not send Gmail email
- does not save state
- does not commit state

Scraper backend
The production default is still Playwright:
SCRAPER_BACKEND=playwright

Direct HTTP scraping can be tested without changing report or email behaviour:
SCRAPER_BACKEND=direct

Temporary fallback mode tries direct HTTP first and falls back to Playwright if direct target resolution or fetching fails:
SCRAPER_BACKEND=direct_with_fallback

Category filters default to rare records only:
ORNITHO_CATEGORIES=rare

To include both rare and very rare records:
ORNITHO_CATEGORIES=rare,veryrare

The GitHub daily and hourly workflows read SCRAPER_BACKEND and ORNITHO_CATEGORIES from repository variables, defaulting to Playwright and rare. This allows a production switch without editing code or the Cloudflare Worker.

Persistent state
The state file is tracked at:
state/state.json

It stores stable hashes of seen records by monitor and target. Record identity is based on:
- date
- location
- count
- species
- scientific name
- detail

State writes are local atomic replacements: a temporary file is written, flushed, and then moved into place.

Important trade-off
Email sending and committing state to GitHub cannot be one atomic transaction.

This project intentionally sends email first, then saves/commits state.

Reason:
- missing a rare-bird alert is worse than receiving a duplicate
- if email fails, state is not advanced and a later run can retry
- if email succeeds but the state commit fails, a duplicate alert may happen later

Workflow logs should make state commit failures visible.

GitHub workflows
Ornitho Daily Monitor
- file: .github/workflows/ornitho.yml
- runs once per day around 20:23 Berlin time
- uses Daily Summary mode
- supports manual dry-run
- commits state only after successful non-dry-run runs

Ornitho Hourly Notifications
- file: .github/workflows/ornitho-notify.yml
- dispatch-only workflow for Notification mode
- production hourly triggering should be done by the external scheduler described below
- uses Notification mode
- currently uses SCRAPER_BACKEND=direct_with_fallback during the cautious direct HTTP rollout
- currently uses ORNITHO_CATEGORIES=rare,veryrare during the cautious direct HTTP rollout
- supports manual dry-run
- commits state only after successful non-dry-run runs

Ornitho Notify Test
- file: .github/workflows/ornitho-notify-test.yml
- manual-only test workflow for Notification mode
- useful before changing production notification scheduling

All workflows that can update state share the same concurrency group:
ornitho-monitor-state

This prevents two workflow runs from updating state at the same time.

External hourly trigger
GitHub native scheduled cron has not created hourly runs reliably for this repository.
The hourly notification workflow is therefore intentionally dispatch-only.

Recommended scheduler: Cloudflare Workers Cron Triggers.

Why:
- independent from GitHub's scheduled workflow system
- low-maintenance managed scheduler
- token can be stored as a Cloudflare Worker secret
- the Worker only needs to call GitHub's workflow dispatch API

GitHub workflow dispatch endpoint:
POST https://api.github.com/repos/jtwareing/ornitho-monitor/actions/workflows/ornitho-notify.yml/dispatches

Headers:
Accept: application/vnd.github+json
Authorization: Bearer <GITHUB_TOKEN>
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json

Body for production hourly notifications:
{
  "ref": "main",
  "inputs": {
    "dry_run": "false"
  }
}

Body for a safe external dry-run test:
{
  "ref": "main",
  "inputs": {
    "dry_run": "true"
  }
}

GitHub token permissions:
- use a fine-grained personal access token
- repository access: jtwareing/ornitho-monitor only
- repository permissions: Actions read/write
- no Contents write permission is needed for dispatching; the workflow uses GITHUB_TOKEN for state commits

Cloudflare Worker code:
export default {
  async scheduled(event, env, ctx) {
    const response = await fetch(
      "https://api.github.com/repos/jtwareing/ornitho-monitor/actions/workflows/ornitho-notify.yml/dispatches",
      {
        method: "POST",
        headers: {
          "Accept": "application/vnd.github+json",
          "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
          "User-Agent": "ornitho-monitor-cloudflare-worker"
        },
        body: JSON.stringify({
          ref: "main",
          inputs: {
            dry_run: "false"
          }
        })
      }
    );

    if (!response.ok) {
      throw new Error(`GitHub workflow dispatch failed: ${response.status} ${await response.text()}`);
    }
  }
};

Cloudflare schedule expression:
23 * * * *

Cloudflare setup:
1. Create a Worker.
2. Add the Worker code above.
3. Add a Worker secret named GITHUB_TOKEN containing the fine-grained GitHub token.
4. Add a Cron Trigger with expression: 23 * * * *
5. Deploy the Worker.
6. Temporarily set dry_run to "true" in the Worker body and trigger/test it once.
7. Confirm a GitHub Actions workflow_dispatch run appears for Ornitho Hourly Notifications.
8. Inspect logs for Mode: notify and DRY_RUN enabled.
9. Set dry_run back to "false" for production.

Required GitHub secrets
- EMAIL_FROM
- EMAIL_TO
- EMAIL_PASSWORD

Local verification
Run unit tests:
python -m unittest discover -s tests

Run Daily Summary safely:
$env:DRY_RUN = "True"
python -m ornitho.main

Run Notification mode safely:
$env:DRY_RUN = "True"
python -m ornitho.main --mode notify

GitHub verification
Trigger dry-run notification workflow:
gh workflow run "Ornitho Hourly Notifications" --repo jtwareing/ornitho-monitor -f dry_run=true

Watch it:
gh run watch <run-id> --repo jtwareing/ornitho-monitor --exit-status

Inspect logs:
gh run view <run-id> --repo jtwareing/ornitho-monitor --log

Download artifacts:
gh run download <run-id> --repo jtwareing/ornitho-monitor --dir output/gh-artifacts

Expected dry-run log lines:
- Mode: notify
- DRY_RUN enabled; email not sent.
- DRY_RUN enabled; state not saved.

Troubleshooting
No email arrived:
- check workflow logs for "Reached email step."
- check "EMAIL_FROM configured", "EMAIL_TO configured", and "EMAIL_PASSWORD configured"
- check whether DRY_RUN was true
- check Gmail app password validity

Duplicate notification arrived:
- check whether previous run failed after sending but before committing state
- inspect state/state.json for the target's seen_record_keys
- inspect workflow logs for state commit failure

No artifact uploaded:
- check whether output/ was created
- check actions/upload-artifact step logs

Playwright failure:
- check Install Playwright and browser dependencies step
- check Run Ornitho monitor step for navigation timeout details

State schema failure:
- state/state.json must contain schema_version 1
- unsupported versions fail loudly so future migrations can be explicit
