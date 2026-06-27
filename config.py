from dataclasses import dataclass
import os
from pathlib import Path

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
