from dataclasses import dataclass
import os
from pathlib import Path


def parse_targets(value: str) -> list[tuple[str, str]]:
    targets = []
    for raw_target in value.split(","):
        raw_target = raw_target.strip()
        if not raw_target:
            continue
        if "-" not in raw_target:
            raise ValueError(f"Target must use STATE-DISTRICT format: {raw_target}")
        state, district = raw_target.split("-", 1)
        targets.append((state.strip().upper(), district.strip().upper()))
    return targets


OUT = Path("output")
OUT.mkdir(exist_ok=True)
STATE_PATH = Path("state/state.json")

TARGETS = [
    ("NI", "OHZ"),
    ("NI", "VER"),
    ("NI", "OL"),
    ("NI", "OL*"),
    ("NI", "DH"),
    ("HB", "HB"),
]


@dataclass(frozen=True)
class Monitor:
    name: str
    email_to: str | None
    targets: list[tuple[str, str]]


MONITORS = [
    Monitor(
        name="default",
        email_to=os.environ.get("EMAIL_TO"),
        targets=TARGETS,
    ),
]


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
