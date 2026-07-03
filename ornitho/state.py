import copy
import hashlib
import json
import os
import tempfile

from config import STATE_PATH

SCHEMA_VERSION = 1
RECORD_KEY_FIELDS = ("date", "location", "count", "species", "scientific", "detail")


def empty_state():
    """Return the current empty state document."""
    return {
        "schema_version": SCHEMA_VERSION,
        "monitors": {},
        "operations": {},
    }


def load_state(path=STATE_PATH):
    """Load state from disk, or return an empty state when no file exists."""
    if not path.exists():
        return empty_state()

    with path.open("r", encoding="utf-8") as state_file:
        state = json.load(state_file)

    return validate_state(state)


def save_state(state, path=STATE_PATH):
    """Persist state as stable, human-readable JSON using an atomic replace."""
    state = validate_state(copy.deepcopy(state))
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_name = None
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as state_file:
        temp_name = state_file.name
        json.dump(state, state_file, indent=2, sort_keys=True)
        state_file.write("\n")
        state_file.flush()
        os.fsync(state_file.fileno())

    os.replace(temp_name, path)


def validate_state(state):
    """Validate and normalize the current state schema."""
    if not isinstance(state, dict):
        raise RuntimeError("State file must contain a JSON object")

    if state.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(f"Unsupported state schema version: {state.get('schema_version')}")

    monitors = state.setdefault("monitors", {})
    if not isinstance(monitors, dict):
        raise RuntimeError("State monitors must be an object")

    operations = state.setdefault("operations", {})
    if not isinstance(operations, dict):
        raise RuntimeError("State operations must be an object")

    handled_failure = operations.get("handled_failure")
    if handled_failure is not None:
        if not isinstance(handled_failure, dict):
            raise RuntimeError("State operations.handled_failure must be an object")
        for key in ("active",):
            if key in handled_failure and not isinstance(handled_failure[key], bool):
                raise RuntimeError(f"State operations.handled_failure.{key} must be true or false")
        for key in (
            "failure_type",
            "first_seen",
            "last_seen",
            "last_alert_sent",
            "last_recovery_sent",
        ):
            if key in handled_failure and handled_failure[key] is not None and not isinstance(
                handled_failure[key],
                str,
            ):
                raise RuntimeError(f"State operations.handled_failure.{key} must be a string or null")
        if "suppressed_count" in handled_failure and not isinstance(
            handled_failure["suppressed_count"],
            int,
        ):
            raise RuntimeError("State operations.handled_failure.suppressed_count must be an integer")

    for monitor_name, monitor_state in monitors.items():
        if not isinstance(monitor_state, dict):
            raise RuntimeError(f"State monitor {monitor_name} must be an object")

        targets = monitor_state.setdefault("targets", {})
        if not isinstance(targets, dict):
            raise RuntimeError(f"State monitor {monitor_name} targets must be an object")

        for label, state_bucket in targets.items():
            if not isinstance(state_bucket, dict):
                raise RuntimeError(f"State target {monitor_name}/{label} must be an object")

            seen = state_bucket.setdefault("seen_record_keys", [])
            if not isinstance(seen, list) or not all(isinstance(key, str) for key in seen):
                raise RuntimeError(f"State target {monitor_name}/{label} seen_record_keys must be a list of strings")

            state_bucket["seen_record_keys"] = sorted(set(seen))

    return state


def record_key(record):
    """Build a stable identity for one Ornitho record from parser fields."""
    identity = {
        field: str(record.get(field, "")).strip()
        for field in RECORD_KEY_FIELDS
    }
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def target_state(state, monitor_name, label):
    """Return the mutable state bucket for one monitor target."""
    monitor_state = state.setdefault("monitors", {}).setdefault(monitor_name, {"targets": {}})
    targets = monitor_state.setdefault("targets", {})
    return targets.setdefault(label, {"seen_record_keys": []})


def seen_record_keys(state, monitor_name, label):
    return set(target_state(state, monitor_name, label).setdefault("seen_record_keys", []))


def identify_new_records(state, monitor_name, label, records):
    """Return records whose identities are not present in saved state."""
    seen = seen_record_keys(state, monitor_name, label)
    return [
        record
        for record in records
        if record_key(record) not in seen
    ]


def compare_current_records(state, monitor_name, all_results):
    """Compare all scraped target results with the saved state."""
    return [
        (label, identify_new_records(state, monitor_name, label, records))
        for label, records in all_results
    ]


def update_state(state, monitor_name, all_results):
    """Return a copy of state updated with all currently scraped records."""
    updated = copy.deepcopy(state)

    for label, records in all_results:
        target = target_state(updated, monitor_name, label)
        keys = set(target.setdefault("seen_record_keys", []))
        keys.update(record_key(record) for record in records)
        target["seen_record_keys"] = sorted(keys)

    return updated
