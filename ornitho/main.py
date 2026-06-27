from playwright.sync_api import sync_playwright

from config import OUT, MONITORS, ATTEMPTS, WAIT_SECONDS, HEADLESS, DRY_RUN
from emailer import send_email
from ornitho.report import build_report
from ornitho.scraper import check_target_with_retry


def run_monitor(browser, monitor):
    all_results = []
    errors = []

    for state, district in monitor.targets:
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

    report = build_report(all_results, errors)
    OUT.joinpath("multi_report.txt").write_text(report, encoding="utf-8")

    print()
    print(report)

    send_email(report, dry_run=DRY_RUN, email_to=monitor.email_to)
    if not DRY_RUN:
        print("Email sent.")


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)

        try:
            for monitor in MONITORS:
                run_monitor(browser, monitor)
        finally:
            browser.close()


if __name__ == "__main__":
    run()
