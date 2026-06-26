import re

DATE_RE = re.compile(r"^[A-Z][a-z]+day, [A-Z][a-z]+ \d{1,2}(st|nd|rd|th), \d{4}$")
COUNT_RE = re.compile(r"^\d+$")
SCI_RE = re.compile(r"^\([A-Z][a-z]+ [a-z]+(?: [a-z]+)?\)$")


def parse_records(text):
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    records = []

    for i, line in enumerate(lines):
        if not DATE_RE.match(line):
            continue
        if i + 4 >= len(lines):
            continue

        location = lines[i + 1]
        count = lines[i + 2]
        species = lines[i + 3]
        scientific = lines[i + 4]

        if not COUNT_RE.match(count):
            continue
        if not SCI_RE.match(scientific):
            continue

        detail = ""
        if i + 5 < len(lines) and lines[i + 5].startswith("Detail"):
            detail = lines[i + 5].replace("Detail :", "").strip()

        records.append({
            "date": line,
            "location": location,
            "count": count,
            "species": species,
            "scientific": scientific.strip("()"),
            "detail": detail,
        })

    return records