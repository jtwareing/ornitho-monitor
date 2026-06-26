from playwright.sync_api import sync_playwright

from config import OUT, TARGETS, ATTEMPTS, WAIT_SECONDS, HEADLESS
from emailer import send_email
from ornitho.report import build_report
from ornitho.scraper import check_target_with_retry


def run():
    all_results = []
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)

        for state, district in TARGETS:
            label = f"{state}-{district}"
            print(f"Checking {label}...")

            try:
                records = check_target_with_retry(
                    browser,
                    state,
                    district,
                    attempts=ATTEMPTS,
                    wait_seconds=WAIT_SECONDS,
                )
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