Ornitho Daily Rare Bird Monitor

Overview
This project monitors selected Ornitho regions with Playwright, extracts rare-bird records, sends email reports, and stores persistent record state in the repository.

The scraper is deliberately separate from reporting, email, and state handling:
- ornitho/scraper.py navigates Ornitho and returns parsed records.
- ornitho/parser.py converts page text into record dictionaries.
- ornitho/report.py builds plain-text daily and notification reports.
- ornitho/state.py loads, compares, updates, and saves persistent state.
- emailer.py sends or dry-runs email.
- ornitho/main.py coordinates monitor execution modes.

Monitors
A monitor is configured in config.py with:
- name
- email_to
- targets

The default monitor currently uses EMAIL_TO from the environment and these targets:
- NI-OHZ
- NI-VER
- NI-OL
- NI-OL*
- NI-DH
- HB-HB

Adding monitors
Add another Monitor entry to MONITORS in config.py with a unique name, recipient, and target list.

Example:
Monitor(
    name="bremen",
    email_to=os.environ.get("EMAIL_TO_BREMEN"),
    targets=[("HB", "HB")],
)

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
- runs once per day at 20:00 Berlin time
- uses Daily Summary mode
- supports manual dry-run
- commits state only after successful non-dry-run runs

Ornitho Hourly Notifications
- file: .github/workflows/ornitho-notify.yml
- runs hourly
- uses Notification mode
- supports manual dry-run
- commits state only after successful non-dry-run runs

Ornitho Notify Test
- file: .github/workflows/ornitho-notify-test.yml
- manual-only test workflow for Notification mode
- useful before changing production notification scheduling

All workflows that can update state share the same concurrency group:
ornitho-monitor-state

This prevents two workflow runs from updating state at the same time.

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
