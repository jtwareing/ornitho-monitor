import argparse

from playwright.sync_api import sync_playwright

from config import (
    OUT,
    MONITORS,
    ATTEMPTS,
    WAIT_SECONDS,
    HEADLESS,
    DRY_RUN,
    STATE_PATH,
    SCRAPER_BACKEND,
    NOTIFY_EXTRA_TARGETS,
)
from emailer import send_email
from ornitho.direct_scraper import CURRENT_OBSERVATIONS_URL, DirectOrnithoScraper
from ornitho.report import build_notification_report, build_report
from ornitho.scraper import check_target_with_retry
from ornitho.state import compare_current_records, load_state, save_state, update_state

DAILY_MODE = "daily"
NOTIFY_MODE = "notify"
NOTIFICATION_SUBJECT = "Ornitho Rare Bird Notification"
PLAYWRIGHT_BACKEND = "playwright"
DIRECT_BACKEND = "direct"
DIRECT_WITH_FALLBACK_BACKEND = "direct_with_fallback"
SCRAPER_BACKENDS = (PLAYWRIGHT_BACKEND, DIRECT_BACKEND, DIRECT_WITH_FALLBACK_BACKEND)


def should_send_report(mode, new_count):
    return mode == DAILY_MODE or new_count > 0


def report_path_for_monitor(monitor_name):
    safe_name = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in monitor_name
    ).strip("_")
    return OUT.joinpath(f"{safe_name or 'monitor'}_report.txt")


def check_target_records(
    browser,
    direct_scraper,
    direct_index_html,
    state_code,
    district,
    backend=PLAYWRIGHT_BACKEND,
    categories=("rare",),
):
    if backend in {DIRECT_BACKEND, DIRECT_WITH_FALLBACK_BACKEND}:
        try:
            result = direct_scraper.check_target(
                (state_code, district),
                index_html=direct_index_html,
                categories=categories,
            )
            print(
                "  Direct HTTP stats: "
                f"requests={result.stats.request_count}, "
                f"pages={result.stats.pages_fetched}, "
                f"records={result.stats.records_parsed}, "
                f"categories={','.join(result.stats.categories)}"
            )
            return result.records
        except Exception as exc:
            if backend == DIRECT_BACKEND:
                raise
            print(f"  Direct HTTP failed; falling back to Playwright: {type(exc).__name__}: {exc}")

    return check_target_with_retry(
        browser,
        state_code,
        district,
        attempts=ATTEMPTS,
        wait_seconds=WAIT_SECONDS,
    )


def run_monitor(
    browser,
    monitor,
    state,
    mode=DAILY_MODE,
    persist_state=True,
    backend=PLAYWRIGHT_BACKEND,
    direct_scraper=None,
    direct_index_html=None,
    extra_targets=(),
):
    all_results = []
    errors = []
    targets = list(monitor.targets)
    categories = monitor.categories[mode]
    print(f"Monitor '{monitor.name}' categories for {mode}: {','.join(categories)}")
    if extra_targets:
        targets.extend(extra_targets)
        print(
            "Temporary notify-only extra targets: "
            + ", ".join(f"{state}-{district}" for state, district in extra_targets)
        )

    for state_code, district in targets:
        label = f"{state_code}-{district}"
        print(f"Checking {label}...")

        try:
            records = check_target_records(
                browser,
                direct_scraper,
                direct_index_html,
                state_code,
                district,
                backend=backend,
                categories=categories,
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

    if mode == NOTIFY_MODE:
        report = build_notification_report(report_results, errors)
    else:
        report = build_report(report_results, errors)
    report_path_for_monitor(monitor.name).write_text(report, encoding="utf-8")
    OUT.joinpath("multi_report.txt").write_text(report, encoding="utf-8")

    print()
    print(report)

    if should_send_report(mode, new_count):
        subject = NOTIFICATION_SUBJECT if mode == NOTIFY_MODE else None
        send_email(report, dry_run=DRY_RUN, email_to=monitor.email_to, subject=subject)
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
    if SCRAPER_BACKEND not in SCRAPER_BACKENDS:
        raise RuntimeError(f"Unsupported SCRAPER_BACKEND: {SCRAPER_BACKEND}")

    state = load_state(STATE_PATH)
    print(f"State loaded from {STATE_PATH}.")
    print(f"Mode: {mode}")
    print(f"Scraper backend: {SCRAPER_BACKEND}")
    if mode == NOTIFY_MODE and NOTIFY_EXTRA_TARGETS:
        print(
            "Notify extra targets: "
            + ", ".join(f"{state}-{district}" for state, district in NOTIFY_EXTRA_TARGETS)
        )

    enabled_monitors = []
    for monitor in MONITORS:
        if monitor.enabled:
            enabled_monitors.append(monitor)
        else:
            print(f"Monitor '{monitor.name}' disabled; skipping.")
    if not enabled_monitors:
        print("No enabled monitors; nothing to do.")
        return

    active_backend = SCRAPER_BACKEND
    direct_scraper = None
    direct_index_html = None
    if SCRAPER_BACKEND in {DIRECT_BACKEND, DIRECT_WITH_FALLBACK_BACKEND}:
        try:
            direct_scraper = DirectOrnithoScraper()
            direct_index_html = direct_scraper.fetch_text(CURRENT_OBSERVATIONS_URL)
        except Exception as exc:
            if SCRAPER_BACKEND == DIRECT_BACKEND:
                raise
            active_backend = PLAYWRIGHT_BACKEND
            direct_scraper = None
            direct_index_html = None
            print(
                "Direct HTTP setup failed; using Playwright fallback: "
                f"{type(exc).__name__}: {exc}"
            )

    if active_backend == DIRECT_BACKEND:
        for monitor in enabled_monitors:
            state = run_monitor(
                None,
                monitor,
                state,
                mode=mode,
                persist_state=not DRY_RUN,
                backend=active_backend,
                direct_scraper=direct_scraper,
                direct_index_html=direct_index_html,
                extra_targets=NOTIFY_EXTRA_TARGETS if mode == NOTIFY_MODE else (),
            )
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)

        try:
            for monitor in enabled_monitors:
                state = run_monitor(
                    browser,
                    monitor,
                    state,
                    mode=mode,
                    persist_state=not DRY_RUN,
                    backend=active_backend,
                    direct_scraper=direct_scraper,
                    direct_index_html=direct_index_html,
                    extra_targets=NOTIFY_EXTRA_TARGETS if mode == NOTIFY_MODE else (),
                )
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
