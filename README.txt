Ornitho Monitor

Version 1.0 Release Candidate

Version 1.0 scope: hourly rare-bird notifications only.

The daily summary workflow is paused for v1.0 because its Playwright path is
not reliable enough in GitHub Actions. The workflow remains manually
dispatchable for diagnostics, but it has no schedule and should not be treated
as production until it is migrated to the direct HTTP backend or otherwise
revalidated.

This project monitors selected Ornitho regions, extracts rare-bird records,
sends email reports, and stores persistent notification state in the
repository.

Further documentation

- ARCHITECTURE.md explains the production architecture, data flow, component
  boundaries, and major design decisions.
- ENGINEERING_PRINCIPLES.md records the durable engineering principles from the
  v1.0 review.
- ADAPTER_GUIDE.md describes how future acquisition adapters should integrate
  with scrape planning, state comparison, notifications, and operations.

Production architecture

The current production path is:

Cloudflare Worker cron
-> GitHub workflow_dispatch
-> Ornitho Hourly Notifications workflow
-> direct HTTP scraper with bounded retries
-> scrape-query fanout across monitors
-> per-monitor state comparison
-> per-monitor email decision
-> state save and Git commit when appropriate
-> run artifact upload

Daily summary is deferred for v1.0. A manual diagnostic workflow remains:

manual dispatch
-> Ornitho Daily Monitor workflow
-> scraper
-> scrape-query fanout across monitors
-> daily report generation
-> dry-run or explicitly requested diagnostic email/state behaviour
-> artifact upload

Core modules

- config.py loads and validates monitor configuration and runtime settings.
- ornitho/direct_scraper.py reads Ornitho's JSON observation endpoint.
- ornitho/scraper.py remains the Playwright scraper used by daily mode and
  manual diagnostics.
- ornitho/main.py coordinates execution, scrape planning, fanout, state,
  reporting, email, and run summaries.
- ornitho/report.py builds plain-text daily and notification reports.
- ornitho/state.py loads, compares, updates, and atomically saves state.
- emailer.py sends email or prints dry-run output.

Monitor configuration

Monitors are configured in monitors.json.

Required top-level field:
- schema_version: currently 1

Each monitor has:
- name: unique monitor name
- enabled: true or false
- email_to or email_to_env: exactly one recipient source
- categories.daily: non-empty list of Ornitho categories for daily summaries
- categories.notify: non-empty list of Ornitho categories for notifications
- targets: list of STATE-DISTRICT target strings

Optional monitor field:
- pause_until: YYYY-MM-DD

Example:

{
  "name": "example",
  "enabled": true,
  "email_to": "recipient@example.com",
  "categories": {
    "daily": ["rare"],
    "notify": ["rare", "veryrare"]
  },
  "targets": ["HB-HB"]
}

The default monitor uses email_to_env=EMAIL_TO and receives the original
production targets:
- NI-OHZ
- NI-VER
- NI-OL
- NI-OL*
- NI-DH
- HB-HB

Simon is configured as a separate monitor with independent targets, recipient,
reports, and notification state.

Configuration validation happens at startup before scraping or sending email.
Invalid JSON, invalid schema_version, invalid targets, missing recipients,
invalid categories, duplicate monitor names, and invalid pause_until values fail
the run clearly.

Scrape planning and fanout

The runner deduplicates work by unique scrape query, not by monitor. A scrape
query includes the target, category set, and backend. Each unique query is
scraped once and then fanned out to every enabled monitor that requested it.

State and email behaviour remain monitor-specific. A record can be new for one
monitor and already seen for another.

Execution modes

Daily Summary:

python -m ornitho.main

- default mode
- sends each enabled monitor a complete current rare-bird report
- preserves the original daily report format
- not part of v1.0 production scheduling

Notification mode:

python -m ornitho.main --mode notify

- intended for hourly runs
- compares current records with state/state.json
- sends only genuinely new records
- sends no user email when there are no new records
- still saves state on successful non-dry-run runs

Dry-run mode

Set DRY_RUN=True.

Dry-run:
- scrapes and compares records
- prints email subject/body
- sends no Gmail email
- saves no state
- commits no state

Scraper backend strategy

Hourly production uses:

SCRAPER_BACKEND=direct_with_retries

This uses direct HTTP only, with bounded setup retries, short backoff, strict
request timeouts, and a workflow timeout. It does not automatically invoke
Playwright.

Daily diagnostic runs currently use the workflow variable SCRAPER_BACKEND when
set, otherwise they default to:

SCRAPER_BACKEND=playwright

Available backends:
- playwright: browser navigation scraper
- direct: direct HTTP scraper
- direct_with_fallback: direct first, then Playwright fallback
- direct_with_retries: bounded direct HTTP retry strategy for hourly production

Playwright remains available for manual daily diagnostics and shadow comparison
workflows. It is not part of the v1.0 hourly production path and is not the
automatic hourly recovery path.

Failure semantics

SUCCESS:
- the run completed normally
- user emails may or may not have been sent depending on new records
- state may be saved on non-dry-run runs
- run_summary.json is uploaded

HANDLED_FAILURE:
- a known bounded scraper/runtime failure occurred, such as direct setup timeout
- no user bird emails are sent
- state is not saved
- scrape_failure.txt is uploaded
- run_summary.json records status HANDLED_FAILURE
- one operational alert is sent if OPERATIONS_EMAIL is configured
- the GitHub job exits successfully to avoid hourly failure-notification spam

Unexpected failure:
- code error
- invalid configuration
- missing required secret
- state corruption
- artifact upload failure
- email-sending error when an email was expected
- any failure outside the known bounded scraper/runtime class

Unexpected failures fail the GitHub workflow. They should be investigated as
defects or operational configuration problems.

State persistence

Persistent state lives at:

state/state.json

It stores stable hashes of seen records by monitor and target. Record identity
uses:
- date
- location
- count
- species
- scientific name
- detail

State writes use an atomic local replacement: write temporary file, flush, then
replace state/state.json.

Email and Git state commit are intentionally not atomic. The system sends email
first, then saves and commits state. This favours not missing rare-bird alerts.
The trade-off is that a successful email followed by a failed state commit can
cause a later duplicate notification.

Operations alerts

Operations alerts are infrastructure alerts, not bird notifications.

Set GitHub secret OPERATIONS_EMAIL to enable them.

Handled-failure alerts are throttled. The first HANDLED_FAILURE sends an
operations alert. Repeated failures of the same type are suppressed for the
configured window, default 6 hours. Every run still uploads run_summary.json and
scrape_failure.txt.

When scraping recovers after handled failures, the monitor sends one recovery
email and clears the active handled-failure alert state.

If OPERATIONS_EMAIL is unset:
- no operational alert is sent
- the run summary records that the alert was skipped
- the system does not fall back to EMAIL_TO or monitor recipients

Operational controls

Disable one monitor:
- set enabled to false in monitors.json
- commit and push

Re-enable one monitor:
- set enabled to true
- commit and push

Pause one monitor:
- add pause_until to that monitor in monitors.json
- format: YYYY-MM-DD
- the monitor is skipped while today's Berlin date is before or equal to
  pause_until

Re-enable one paused monitor:
- remove pause_until, or set it to a past date
- commit and push

Global emergency shutdown:
- set repository variable ORNITHO_MONITORING_DISABLED=true
- hourly user monitoring skips all monitors before scraping
- no user notification emails are sent
- no state is saved
- operational alerts still work for unexpected failures

Re-enable globally:
- set ORNITHO_MONITORING_DISABLED=false, or remove the variable

Production configuration

GitHub Actions secrets:
- EMAIL_FROM: sender Gmail address
- EMAIL_PASSWORD: Gmail app password
- EMAIL_TO: default monitor recipient used by email_to_env=EMAIL_TO
- OPERATIONS_EMAIL: maintainer alert recipient

GitHub repository variables:
- SCRAPER_BACKEND: optional manual daily diagnostic override; defaults to
  playwright
- ORNITHO_MONITORING_DISABLED: optional global shutdown flag
- OPERATIONS_ALERT_THROTTLE_HOURS: optional operations alert throttle window;
  defaults to 6

Current note:
- ORNITHO_CATEGORIES is not a production control in v1.0. Categories are
  configured per monitor in monitors.json.
- EMAIL_TO is currently consumed as a GitHub secret, not as a repository
  variable, because it is referenced by monitors.json through email_to_env.

Cloudflare configuration:
- Worker secret GITHUB_TOKEN: fine-grained GitHub token for this repository
- token permission: Actions read/write
- cron schedule: 23 * * * *
- dispatch endpoint:
  POST https://api.github.com/repos/jtwareing/ornitho-monitor/actions/workflows/ornitho-notify.yml/dispatches
- production body:
  {"ref":"main","inputs":{"dry_run":"false"}}

GitHub workflows

Ornitho Hourly Notifications:
- file: .github/workflows/ornitho-notify.yml
- dispatch-only
- triggered hourly by Cloudflare
- mode: notify
- backend: direct_with_retries
- uploads ornitho-notify-report artifact
- commits state only after successful non-dry-run runs with state changes

Ornitho Daily Monitor:
- file: .github/workflows/ornitho.yml
- manual dispatch only for v1.0 diagnostics
- no schedule, so no daily scheduled emails are sent
- mode: daily
- uploads ornitho-report artifact

Ornitho Notify Test:
- file: .github/workflows/ornitho-notify-test.yml
- manual-only notification-mode test workflow

Ornitho Direct Shadow Compare:
- file: .github/workflows/ornitho-direct-shadow-compare.yml
- manual-only diagnostic comparison of Playwright and direct HTTP
- sends no email and saves no state

All workflows that can update state share concurrency group:

ornitho-monitor-state

Operator guide

Add a new monitor:
1. Edit monitors.json.
2. Add a monitor with unique name, recipient, categories, and targets.
3. Run unit tests locally.
4. Trigger Ornitho Hourly Notifications with dry_run=true.
5. Inspect run_summary.json.
6. Confirm records and recipient routing are monitor-specific.
7. Commit and push.

Pause a monitor:
1. Add "pause_until": "YYYY-MM-DD" to that monitor.
2. Commit and push.
3. Trigger a dry-run.
4. Confirm run_summary.json lists the monitor under monitors_skipped.

Disable a monitor:
1. Set enabled=false.
2. Commit and push.
3. Trigger a dry-run.
4. Confirm the monitor is skipped before scrape planning.

Global shutdown:
1. Set GitHub repository variable ORNITHO_MONITORING_DISABLED=true.
2. Observe the next hourly run or trigger a dry-run.
3. Confirm no user monitoring occurs and no state is saved.

Rollback:
1. Find the previous working commit in GitHub Actions or git log.
2. Revert the bad commit:
   git revert <commit-sha>
3. Push main.
4. Trigger Ornitho Hourly Notifications with dry_run=true.
5. Inspect logs and run_summary.json before returning to production.

Inspect GitHub artifacts:
1. Open the workflow run in GitHub Actions.
2. Download the uploaded artifact.
3. For hourly runs, inspect ornitho-notify-report/run_summary.json.
4. If present, inspect scrape_failure.txt.

Using GitHub CLI:

gh run view <run-id> --repo jtwareing/ornitho-monitor --log
gh run download <run-id> --repo jtwareing/ornitho-monitor --dir output/gh-artifacts

Interpret run_summary.json:
- overall_run_status: SUCCESS, HANDLED_FAILURE, or FAILED
- dry_run: whether user email/state writes were disabled
- active_backend: scraper backend actually used
- monitors_loaded/enabled/skipped: monitor routing
- unique_scrape_queries_planned: fanout deduplication count
- actual_scrape_queries_executed: completed scrape count
- records_per_monitor: per-monitor record counts where available
- emails: user and operations email decisions
- operations: alert throttle and recovery decisions
- state: whether state was saved or skipped

Interpret HANDLED_FAILURE:
- this is usually an Ornitho/direct HTTP availability problem
- no user bird email was sent
- state was not saved
- operational alert is sent if OPERATIONS_EMAIL is configured and the throttle
  window allows it
- GitHub job success is expected

Recover from repeated scraper failures:
1. Confirm failures are HANDLED_FAILURE, not unexpected workflow failures.
2. Inspect scrape_failure.txt for timeout or HTTP errors.
3. Check whether Ornitho is reachable manually.
4. If the failure is persistent, set ORNITHO_MONITORING_DISABLED=true to stop
   user monitoring noise.
5. Use the manual Direct Shadow Compare workflow or local diagnostics to
   determine whether direct HTTP or Ornitho changed.
6. Re-enable only after a dry-run succeeds or the failure mode is understood.

Local verification

Run all unit tests:

python -m unittest discover -s tests

Compile check:

python -m compileall config.py emailer.py ornitho tests

Safe daily run:

$env:DRY_RUN = "True"
python -m ornitho.main

Safe notification run:

$env:DRY_RUN = "True"
python -m ornitho.main --mode notify

Release checklist

[ ] Cloudflare Worker configured
[ ] Cloudflare Worker secret GITHUB_TOKEN configured
[ ] Cloudflare cron trigger configured
[ ] GitHub secrets configured
[ ] GitHub repository variables configured
[ ] OPERATIONS_EMAIL verified
[ ] Hourly workflow verified
[ ] Daily workflow schedule disabled
[ ] Direct HTTP backend verified
[ ] Fanout verified
[ ] Multi-monitor routing verified
[ ] State save/skip behaviour verified
[ ] Artifacts verified
[ ] Documentation complete

Troubleshooting

No bird email arrived:
- check whether the run was dry-run
- check whether there were new records
- check EMAIL_FROM, EMAIL_TO, and EMAIL_PASSWORD configuration log lines
- inspect run_summary.json emails.user_sent and emails.user_skipped

No operational alert arrived:
- check OPERATIONS_EMAIL configured log line
- inspect run_summary.json emails.operations_alert_sent
- inspect run_summary.json emails.operations_alert_skipped_reason for throttle
  suppression
- confirm the failure was a handled or unexpected failure requiring an alert

Duplicate notification arrived:
- check whether a previous run sent email but failed before committing state
- inspect state/state.json for the monitor history
- inspect workflow logs for state commit failure

No state commit:
- dry-run never commits state
- HANDLED_FAILURE never commits state
- no-record successful runs may leave state unchanged
- commit step logs "State unchanged; nothing to commit." when appropriate

Invalid config:
- fix monitors.json
- rerun tests
- trigger a dry-run before returning to production

Version 1.0 readiness definition

v1.0 is ready when the hourly notification system is verified with:
- Cloudflare dispatch
- multi-monitor configuration
- direct HTTP bounded runtime
- scrape-query fanout
- persistent per-monitor state
- operational alerts
- uploaded run artifacts
- daily summary schedule disabled

Daily summary is explicitly deferred beyond v1.0.
