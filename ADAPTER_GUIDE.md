# Acquisition Adapter Guide

This guide explains how a future acquisition adapter should fit into the
monitoring architecture.

## Adapter Purpose

An adapter connects one external data source to the common event-detection
pipeline. It is responsible for acquiring source data and returning normalised
records. It should not decide who receives notifications or how monitor state is
updated.

## Expected Inputs

An adapter should be driven by scrape queries produced by the planning layer.
A query should describe the real data request, not the requesting monitor.

Typical query fields:

- source or backend
- target or region
- category/filter set
- pagination or endpoint parameters when relevant

## Expected Output

The adapter should return records in a stable dictionary-like shape. For
Ornitho, the normalised record fields are:

- `date`
- `location`
- `count`
- `species`
- `scientific`
- `detail`
- `rarity`

Future adapters may add fields, but they should preserve a clear event identity
model. Downstream comparison depends on stable fields, not raw source markup.

## Normalisation Rules

Normalisation should:

- remove source-specific HTML or markup,
- preserve meaningful counts and ranges,
- preserve comments/details that affect event identity,
- preserve source category/rarity where available,
- avoid inventing values that the source did not provide,
- produce deterministic output for the same source record.

If source data is incomplete or ambiguous, prefer an explicit handled failure or
empty result over misleading records.

## Handled Failures

Adapters should raise a known bounded runtime failure for expected acquisition
problems, such as:

- source timeout,
- source unavailable,
- pagination timeout,
- endpoint temporarily failing,
- target resolution failure caused by source instability.

Handled failures must be clear enough for the orchestrator to:

- send no user notification,
- avoid advancing user notification state,
- write failure artifacts,
- throttle operational alerts,
- recover cleanly later.

Unexpected code errors should remain unexpected failures.

## Flow Into The Pipeline

Adapter output flows through:

```text
adapter records
-> scrape fanout
-> per-monitor state comparison
-> per-monitor notification decision
-> state update after successful run
-> run summary and artifacts
```

The adapter should not know about monitor recipients, Gmail, state commits, or
operational alert throttling.

## Testing Requirements

Each adapter should include:

- fixture responses for representative successful data,
- empty/no-record fixtures,
- malformed/unexpected response fixtures,
- pagination tests if the source paginates,
- timeout/failure tests,
- record normalisation tests,
- tests proving no partial/bad data advances state.

Fixtures must not contain credentials, private tokens, or sensitive personal
data.

## Production Readiness Requirements

Before an adapter becomes production:

- it must have bounded runtime,
- it must produce useful run summaries,
- it must classify handled failures,
- it must have regression fixtures,
- it must have dry-run evidence,
- it must not send user notifications from untrusted partial data,
- it must be observed in production-like runs.

## Avoid Premature Generalisation

Do not abstract the adapter interface beyond what real adapters prove is needed.
The second real adapter should reveal which concepts are shared and which are
Ornitho-specific. Generalise from evidence, not from imagined future sources.
