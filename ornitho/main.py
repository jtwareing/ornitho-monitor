import argparse

from playwright.sync_api import sync_playwright

from config import OUT, MONITORS, ATTEMPTS, WAIT_SECONDS, HEADLESS, DRY_RUN, STATE_PATH
from emailer import send_email
from ornitho.report import build_report
from ornitho.scraper import check_target_with_retry
from ornitho.state import compare_current_records, load_state, save_state, update_state

DAILY_MODE = "daily"
NOTIFY_MODE = "notify"


def should_send_report(mode, new_count):
    return mode == DAILY_MODE or new_count > 0


def run_monitor(browser, monitor, state, mode=DAILY_MODE, persist_state=True):
    all_results = []
    errors = []

    for state_code, district in monitor.targets:
        label = f"{state_code}-{district}"
        print(f"Checking {label}...")

        try:
            records = check_target_with_retry(
                browser,
                state_code,
                district,
                attempts=ATTEMPTS,
                wait_seconds=WAIT_SECONDS,
            )
            all_results.append((label, records))
            print(f"  Records extracted: {len(records)}")
        except Exception as e:
            errors.append((label, type(e).__name__, str(e)))
            print(f"  Error after retries: {type(e).__name__}: {e}")

    new_results = compare_current_records(state, monitor.name, all_results)
    new_count = sum(len(records) for _, records in new_results)
    print(f"New records since previous state for monitor '{monitor.name}': {new_count}")

    updated_state = update_state(state, monitor.name, all_results)
    report_results = new_results if mode == NOTIFY_MODE else all_results

    report = build_report(report_results, errors)
    OUT.joinpath("multi_report.txt").write_text(report, encoding="utf-8")

    print()
    print(report)

    if should_send_report(mode, new_count):
        send_email(report, dry_run=DRY_RUN, email_to=monitor.email_to)
        if not DRY_RUN:
            print("Email sent.")
    else:
        print(f"No new records for monitor '{monitor.name}'; notification email not sent.")

    if persist_state:
        save_state(updated_state, STATE_PATH)
        print(f"State saved to {STATE_PATH}.")
        return updated_state

    print("DRY_RUN enabled; state not saved.")
    return state


def run(mode=DAILY_MODE):
    state = load_state(STATE_PATH)
    print(f"State loaded from {STATE_PATH}.")
    print(f"Mode: {mode}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)

        try:
            for monitor in MONITORS:
                state = run_monitor(browser, monitor, state, mode=mode, persist_state=not DRY_RUN)
        finally:
            browser.close()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=(DAILY_MODE, NOTIFY_MODE),
        default=DAILY_MODE,
        help="daily sends the full report; notify sends only genuinely new records.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(mode=args.mode)
