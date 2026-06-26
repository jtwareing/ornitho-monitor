from datetime import date
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import re

from config import OUT, TARGETS, ATTEMPTS, WAIT_SECONDS, HEADLESS
from emailer import send_email

DATE_RE = re.compile(r"^[A-Z][a-z]+day, [A-Z][a-z]+ \d{1,2}(st|nd|rd|th), \d{4}$")
COUNT_RE = re.compile(r"^\d+$")
SCI_RE = re.compile(r"^\([A-Z][a-z]+ [a-z]+(?: [a-z]+)?\)$")


def safe_filename(text):
    return text.replace("*", "star").replace("/", "_")


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


def click_no_wait(locator, timeout=15000):
    locator.click(timeout=timeout, no_wait_after=True)


def check_target(browser, state, district):
    page = browser.new_page()
    page.set_default_timeout(15000)

    try:
        page.goto("https://www.ornitho.de/", wait_until="domcontentloaded", timeout=30000)
        click_no_wait(page.get_by_role("emphasis").nth(1))
        page.wait_for_timeout(1000)

        click_no_wait(page.get_by_text("Current observations"))
        page.wait_for_timeout(5000)

        click_no_wait(page.get_by_role("link", name=state, exact=True))
        page.wait_for_timeout(2000)

        click_no_wait(page.get_by_text(district, exact=True))
        page.wait_for_timeout(2000)

        click_no_wait(page.get_by_text("rare", exact=True))
        page.wait_for_timeout(5000)

        html = page.content()
        text = BeautifulSoup(html, "lxml").get_text("\n", strip=True)

        label = f"{state}-{district}"
        file_label = safe_filename(label)
        OUT.joinpath(f"{file_label}_last_page.html").write_text(html, encoding="utf-8")
        OUT.joinpath(f"{file_label}_last_page_text.txt").write_text(text, encoding="utf-8")

        return parse_records(text)

    finally:
        page.close()


def check_target_with_retry(browser, state, district, attempts=ATTEMPTS, wait_seconds=WAIT_SECONDS):
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            if attempt > 1:
                print(f"  Waiting {wait_seconds} seconds before retry {attempt}...")
                wait_page = browser.new_page()
                wait_page.wait_for_timeout(wait_seconds * 1000)
                wait_page.close()
                print(f"  Retry attempt {attempt}...")

            return check_target(browser, state, district)

        except Exception as e:
            last_error = e
            print(f"  Attempt {attempt} failed: {type(e).__name__}: {e}")

    raise last_error


def build_report(all_results, errors):
    today = date.today().isoformat()
    total_records = sum(len(records) for _, records in all_results)

    report_lines = [f"Ornitho rare-bird report — today: {today}", ""]

    if total_records == 0 and not errors:
        report_lines.append("No rare records today.")
        report_lines.append("")

    for label, records in all_results:
        report_lines.append(f"[{label}]")

        if records:
            for r in records:
                report_lines.append(f"{r['species']} ({r['scientific']})")
                report_lines.append(f"{r['count']} — {r['location']}")
                report_lines.append(r["date"])
                if r["detail"]:
                    report_lines.append(f"Detail: {r['detail']}")
                report_lines.append("")
        else:
            report_lines.append("No rare records extracted.")
            report_lines.append("")

    if errors:
        report_lines.append("Errors:")
        for label, err_type, message in errors:
            report_lines.append(f"- {label}: {err_type}: {message}")
        report_lines.append("")

    return "\n".join(report_lines)


def run():
    all_results = []
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)

        for state, district in TARGETS:
            label = f"{state}-{district}"
            print(f"Checking {label}...")

            try:
                records = check_target_with_retry(browser, state, district)
                all_results.append((label, records))
                print(f"  Records extracted: {len(records)}")
            except Exception as e:
                errors.append((label, type(e).__name__, str(e)))
                print(f"  Error after retries: {type(e).__name__}: {e}")

        browser.close()

    report = build_report(all_results, errors)
    OUT.joinpath("multi_report.txt").write_text(report, encoding="utf-8")

    print()
    print(report)

    send_email(report)
    print("Email sent.")


if __name__ == "__main__":
    run()