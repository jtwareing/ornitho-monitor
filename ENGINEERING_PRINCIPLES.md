# Engineering Principles

These principles capture the durable lessons from the v1.0 work.

## Challenge Assumptions First

When a path is not converging, reassess the architecture before refining the
same implementation. The largest gains came from replacing weak assumptions,
not polishing them.

## Optimise For Outcome

The goal is reliable notification, not preserving the original design. Evidence
should outweigh precedent.

## Separate Domain Logic From Operational Logic

Bird records, monitor state, and notification decisions are separate from
source outages, retries, alert throttling, and recovery reporting.

## Separate User Events From Operational Events

A rare bird is a user event. A scraper timeout is an operational event. They
must use separate recipients, state, and reporting.

## No Data Is Better Than Bad Data

If acquisition is untrustworthy, send no user notification and do not advance
user notification state.

## Update State Only After Trustworthy Observations

State represents what the system has safely observed and acted on. Failed or
partial acquisition must not suppress future alerts.

## Bounded Failure Beats Heroic Recovery

Hourly systems need predictable runtime. Bounded failure with clear artifacts is
better than long uncertain recovery.

## Observability Is Part Of Correctness

A run is not operationally useful unless it explains what happened, what was
sent or skipped, and what state changed or did not change.

## Prefer Configuration Over Code

Routine operational changes, such as monitor targets, recipients, categories,
pause dates, and global disable, should not require Python code edits.

## Generalise After Evidence

Do not build a generic platform from one adapter. Add another real adapter
first, learn from the differences, then abstract.

## Keep Failure Modes Explicit

Known bounded source failures, invalid configuration, state corruption, and
email errors have different consequences. Do not collapse them into a generic
"failed" status.
