from pathlib import Path

OUT = Path("output")
OUT.mkdir(exist_ok=True)

TARGETS = [
    ("NI", "OHZ"),
    ("NI", "VER"),
    ("NI", "OL"),
    ("NI", "OL*"),
    ("NI", "DH"),
]

ATTEMPTS = 5
WAIT_SECONDS = 20
HEADLESS = False