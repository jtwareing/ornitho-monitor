# Ornitho Monitor Architecture

This document describes the v1.0 production architecture. It focuses on how the
system works today and why the major decisions were made.

## Current Production Architecture

Version 1.0 is an hourly rare-bird notification product. The daily summary path
is paused and remains available only as a manual diagnostic workflow.

The production execution path is:

```text
Cloudflare Worker cron
-> GitHub workflow_dispatch
-> Ornitho Hourly Notifications workflow
-> direct HTTP acquisition with bounded retries
-> scrape planning and fanout
-> per-monitor state comparison
-> per-monitor notification decision
-> email and state update when appropriate
-> run artifacts and operational alerts
```

## Data Flow

1. Cloudflare dispatches `.github/workflows/ornitho-notify.yml` hourly.
2. GitHub Actions checks out the repository and loads `monitors.json`.
3. The runner validates config before scraping or sending email.
4. Enabled, unpaused monitors are converted into scrape requests.
5. Requests are deduplicated into unique scrape queries.
6. The acquisition backend fetches records once per unique query.
7. Results are fanned out to each requesting monitor.
8. State comparison identifies genuinely new records per monitor.
9. User notifications are sent only for new records.
10. State is saved after successful non-dry-run runs.
11. `run_summary.json` is always uploaded; `scrape_failure.txt` is uploaded on
    handled scraper failures.

## Main Components

- `config.py`: environment and monitor configuration validation.
- `monitors.json`: production monitor definitions.
- `ornitho/main.py`: run orchestration, scrape planning, fanout, email decisions,
  state updates, and run summaries.
- `ornitho/direct_scraper.py`: direct HTTP acquisition from Ornitho JSON
  endpoints.
- `ornitho/scraper.py`: Playwright diagnostic scraper.
- `ornitho/state.py`: persistent user and operational state.
- `ornitho/report.py`: plain-text reports.
- `emailer.py`: email sending and dry-run output.
- `.github/workflows/ornitho-notify.yml`: hourly notification workflow.

## Monitor Configuration

Each monitor defines:

- `name`
- `enabled`
- optional `pause_until`
- one recipient source: `email_to` or `email_to_env`
- per-mode categories
- target districts

Monitor state is independent. The same record may be new for one monitor and
already seen for another.

## Scrape Planning And Fanout

The system deduplicates by scrape query, not by monitor. A scrape query is the
actual data request needed by the acquisition layer:

```text
target + categories + backend-relevant parameters
```

Each unique query is fetched once. The resulting records are distributed to all
monitors that requested the query. This reduces runtime and moves the system
toward a service model: acquire observations once, distribute to subscribers.

## Acquisition Layer

The production acquisition backend is direct HTTP:

```text
SCRAPER_BACKEND=direct_with_retries
```

It resolves configured targets, queries Ornitho JSON data, paginates records,
and returns normalised record dictionaries. It uses bounded setup retries and
timeouts.

Playwright remains available for manual diagnostics and shadow comparison, but
is not part of the hourly production recovery path.

## Decision Engine

The decision engine receives normalised records and monitor state. It decides:

- which records are new for each monitor,
- whether a user notification should be sent,
- whether state should be updated,
- whether an operational condition should be reported.

The acquisition layer does not decide notification behaviour.

## State Model

Persistent state lives in `state/state.json`.

User notification state is scoped by monitor and target. Record identity uses:

- date
- location
- count
- species
- scientific name
- detail

Operational alert state is stored separately under the state document's
operations section. It supports throttled handled-failure alerts and recovery
notifications. It must not advance user notification history.

State writes use atomic local replacement. State is then committed back to the
repository by GitHub Actions when appropriate.

## Notification Model

User notifications and operational alerts are separate.

User notifications:

- are monitor-specific,
- go to monitor recipients,
- include only genuinely new records in notification mode,
- are never sent on handled scraper failure.

Operational alerts:

- go only to `OPERATIONS_EMAIL`,
- report infrastructure/source failures,
- are throttled for repeated handled failures,
- include recovery notifications after successful scraping resumes.

## Operations And Observability

Every hourly run uploads `run_summary.json`.

Handled scraper failures also upload `scrape_failure.txt`.

Important summary fields:

- `overall_run_status`
- `active_backend`
- `dry_run`
- `monitors_loaded`
- `monitors_enabled`
- `monitors_skipped`
- `unique_scrape_queries_planned`
- `actual_scrape_queries_executed`
- `records_per_monitor`
- `emails`
- `operations`
- `state`

## Failure Semantics

`SUCCESS` means the run completed normally. It may or may not have sent user
emails depending on whether new records existed.

`HANDLED_FAILURE` means a known bounded scraper/runtime failure occurred. No
user bird emails are sent, user notification state is not advanced, artifacts
are uploaded, and the GitHub job exits successfully to avoid hourly failure
spam.

Unexpected failures still fail the workflow. Examples include invalid config,
state corruption, code errors, missing required secrets, artifact upload
failure, or email-sending errors when an email was expected.

## Architectural Decisions Timeline

### GitHub Schedule To Cloudflare Dispatch

GitHub scheduled workflows did not reliably create hourly runs. Cloudflare Cron
Triggers now call GitHub's workflow dispatch API. This separates scheduling from
execution and made hourly triggering reliable.

### Playwright To Direct HTTP

Browser navigation was slow and fragile. Network inspection showed Ornitho data
could be acquired directly from JSON endpoints. Direct HTTP became the
production backend; Playwright remains diagnostic only.

### Monitor-Owned Scraping To Scrape Fanout

The original model scraped per monitor. Fanout deduplicates identical data
requests and then distributes results to monitors. This improves runtime and
keeps state and notification decisions monitor-specific.

### Indefinite Recovery To Bounded Handled Failure

Long retries created 20-50 minute workflows. Hourly production now uses bounded
runtime and clear handled failures. Missing one scrape is preferable to tying up
the system in uncertain recovery.

### Mixed User/Ops Emails To Separate Operational Alerts

Operational failures are not user bird events. Operations alerts now go to
`OPERATIONS_EMAIL`, with throttling and recovery notices. User recipients do not
receive infrastructure alerts.

### Daily Summary To Hourly-Only V1.0

The daily summary path still depended on Playwright and exposed reliability
risk. It was paused for v1.0. The production product is hourly notification
only.
