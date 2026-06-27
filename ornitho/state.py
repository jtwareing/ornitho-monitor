import copy
import hashlib
import json

from config import STATE_PATH

SCHEMA_VERSION = 1
RECORD_KEY_FIELDS = ("date", "location", "count", "species", "scientific", "detail")


def empty_state():
    """Return the current empty state document."""
    return {
        "schema_version": SCHEMA_VERSION,
        "monitors": {},
    }


def load_state(path=STATE_PATH):
    """Load state from disk, or return an empty state when no file exists."""
    if not path.exists():
        return empty_state()

    with path.open("r", encoding="utf-8") as state_file:
        state = json.load(state_file)

    if state.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(f"Unsupported state schema version: {state.get('schema_version')}")

    state.setdefault("monitors", {})
    return state


def save_state(state, path=STATE_PATH):
    """Persist state as stable, human-readable JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as state_file:
        json.dump(state, state_file, indent=2, sort_keys=True)
        state_file.write("\n")


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
