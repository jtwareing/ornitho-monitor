from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path


class MonitorConfigError(RuntimeError):
    pass


def parse_target(value: str, context: str = "target") -> tuple[str, str]:
    if not isinstance(value, str) or "-" not in value:
        raise MonitorConfigError(f"{context} must use STATE-DISTRICT format: {value!r}")

    state, district = value.split("-", 1)
    state = state.strip().upper()
    district = district.strip().upper()
    if not state or not district:
        raise MonitorConfigError(f"{context} must include both state and district: {value!r}")
    return state, district


def parse_targets(value: str) -> list[tuple[str, str]]:
    targets = []
    for raw_target in value.split(","):
        raw_target = raw_target.strip()
        if raw_target:
            targets.append(parse_target(raw_target, context="Target"))
    return targets


@dataclass(frozen=True)
class Monitor:
    name: str
    email_to: str | None
    targets: list[tuple[str, str]]


OUT = Path("output")
OUT.mkdir(exist_ok=True)
STATE_PATH = Path("state/state.json")
MONITORS_CONFIG_PATH = Path(os.environ.get("ORNITHO_MONITORS_CONFIG", "monitors.json"))


def load_json_config(path: Path) -> dict:
    if not path.exists():
        raise MonitorConfigError(f"Monitor configuration file not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MonitorConfigError(f"Invalid JSON in monitor configuration {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise MonitorConfigError("Monitor configuration root must be a JSON object")
    return data


def resolve_email_to(raw_monitor: dict, context: str) -> str | None:
    has_email_to = "email_to" in raw_monitor
    has_email_to_env = "email_to_env" in raw_monitor
    if has_email_to == has_email_to_env:
        raise MonitorConfigError(f"{context} must define exactly one of email_to or email_to_env")

    if has_email_to:
        email_to = raw_monitor["email_to"]
        if not isinstance(email_to, str) or not email_to.strip():
            raise MonitorConfigError(f"{context}.email_to must be a non-empty string")
        return email_to.strip()

    email_to_env = raw_monitor["email_to_env"]
    if not isinstance(email_to_env, str) or not email_to_env.strip():
        raise MonitorConfigError(f"{context}.email_to_env must be a non-empty string")
    return os.environ.get(email_to_env.strip())


def parse_monitor(raw_monitor: object, index: int) -> Monitor:
    context = f"monitors[{index}]"
    if not isinstance(raw_monitor, dict):
        raise MonitorConfigError(f"{context} must be an object")

    name = raw_monitor.get("name")
    if not isinstance(name, str) or not name.strip():
        raise MonitorConfigError(f"{context}.name must be a non-empty string")
    name = name.strip()

    raw_targets = raw_monitor.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise MonitorConfigError(f"{context}.targets must be a non-empty list")

    targets = [
        parse_target(raw_target, context=f"{context}.targets[{target_index}]")
        for target_index, raw_target in enumerate(raw_targets)
    ]

    return Monitor(name=name, email_to=resolve_email_to(raw_monitor, context), targets=targets)


def load_monitors(path: Path = MONITORS_CONFIG_PATH) -> list[Monitor]:
    raw_config = load_json_config(path)
    raw_monitors = raw_config.get("monitors")
    if not isinstance(raw_monitors, list) or not raw_monitors:
        raise MonitorConfigError("Monitor configuration must define a non-empty monitors list")

    monitors = [parse_monitor(raw_monitor, index) for index, raw_monitor in enumerate(raw_monitors)]
    names = [monitor.name for monitor in monitors]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise MonitorConfigError(f"Monitor names must be unique: {', '.join(duplicates)}")
    return monitors


MONITORS = load_monitors()
TARGETS = MONITORS[0].targets

ATTEMPTS = 5
WAIT_SECONDS = 20
HEADLESS = False
DRY_RUN = os.environ.get("DRY_RUN", "False").strip().lower() in {"1", "true", "yes", "on"}
SCRAPER_BACKEND = os.environ.get("SCRAPER_BACKEND", "playwright").strip().lower()
ORNITHO_CATEGORIES = tuple(
    category.strip().lower().replace("-", "")
    for category in os.environ.get("ORNITHO_CATEGORIES", "rare").split(",")
    if category.strip()
)
NOTIFY_EXTRA_TARGETS = parse_targets(os.environ.get("ORNITHO_NOTIFY_EXTRA_TARGETS", ""))
