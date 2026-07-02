import argparse
from dataclasses import dataclass
import time

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
    DIRECT_HTTP_TIMEOUT_SECONDS,
    DIRECT_SETUP_ATTEMPTS,
    DIRECT_RETRY_BACKOFF_SECONDS,
    DIRECT_TOTAL_TIMEOUT_SECONDS,
)
from emailer import send_email
from ornitho.direct_scraper import CURRENT_OBSERVATIONS_URL, DirectOrnithoScraper, fetch_text_with_timeout
from ornitho.report import build_notification_report, build_report
from ornitho.scraper import check_target_with_retry
from ornitho.state import compare_current_records, load_state, save_state, update_state

DAILY_MODE = "daily"
NOTIFY_MODE = "notify"
NOTIFICATION_SUBJECT = "Ornitho Rare Bird Notification"
PLAYWRIGHT_BACKEND = "playwright"
DIRECT_BACKEND = "direct"
DIRECT_WITH_FALLBACK_BACKEND = "direct_with_fallback"
DIRECT_WITH_RETRIES_BACKEND = "direct_with_retries"
DIRECT_BACKENDS = (DIRECT_BACKEND, DIRECT_WITH_FALLBACK_BACKEND, DIRECT_WITH_RETRIES_BACKEND)
SCRAPER_BACKENDS = (
    PLAYWRIGHT_BACKEND,
    DIRECT_BACKEND,
    DIRECT_WITH_FALLBACK_BACKEND,
    DIRECT_WITH_RETRIES_BACKEND,
)


class DirectScraperRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScrapeQuery:
    state_code: str
    district: str
    categories: tuple[str, ...]
    backend: str

    @property
    def label(self):
        return f"{self.state_code}-{self.district}"


@dataclass(frozen=True)
class MonitorScrapeRequest:
    monitor_name: str
    label: str
    query: ScrapeQuery


def should_send_report(mode, new_count):
    return mode == DAILY_MODE or new_count > 0


def report_path_for_monitor(monitor_name):
    safe_name = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in monitor_name
    ).strip("_")
    return OUT.joinpath(f"{safe_name or 'monitor'}_report.txt")


def write_failure_artifact(message):
    OUT.mkdir(exist_ok=True)
    OUT.joinpath("scrape_failure.txt").write_text(message + "\n", encoding="utf-8")


def remaining_seconds(deadline):
    if deadline is None:
        return None
    return deadline - time.monotonic()


def ensure_time_remaining(deadline, context):
    remaining = remaining_seconds(deadline)
    if remaining is not None and remaining <= 0:
        raise DirectScraperRuntimeError(f"Direct HTTP total timeout exceeded before {context}")


def bounded_fetch_text(deadline=None):
    def fetch(url):
        remaining = remaining_seconds(deadline)
        if remaining is not None:
            if remaining <= 0:
                raise TimeoutError("Direct HTTP total timeout exceeded")
            timeout = min(DIRECT_HTTP_TIMEOUT_SECONDS, max(1, remaining))
        else:
            timeout = DIRECT_HTTP_TIMEOUT_SECONDS
        return fetch_text_with_timeout(url, timeout=timeout)

    return fetch


def sleep_with_deadline(seconds, deadline):
    remaining = remaining_seconds(deadline)
    if remaining is not None and remaining <= 0:
        raise DirectScraperRuntimeError("Direct HTTP total timeout exceeded before retry backoff")
    time.sleep(min(seconds, remaining) if remaining is not None else seconds)


def fetch_direct_index_with_retries(direct_scraper, deadline=None):
    last_error = None
    for attempt in range(1, DIRECT_SETUP_ATTEMPTS + 1):
        ensure_time_remaining(deadline, "direct setup")
        started = time.perf_counter()
        try:
            print(f"Direct HTTP setup attempt {attempt}/{DIRECT_SETUP_ATTEMPTS}...")
            index_html = direct_scraper.fetch_text(CURRENT_OBSERVATIONS_URL)
            print(f"Direct HTTP setup succeeded in {time.perf_counter() - started:.2f}s.")
            return index_html
        except Exception as exc:
            last_error = exc
            print(
                "Direct HTTP setup attempt "
                f"{attempt}/{DIRECT_SETUP_ATTEMPTS} failed after "
                f"{time.perf_counter() - started:.2f}s: {type(exc).__name__}: {exc}"
            )
            if attempt < DIRECT_SETUP_ATTEMPTS:
                sleep_with_deadline(DIRECT_RETRY_BACKOFF_SECONDS, deadline)

    message = (
        "Direct HTTP setup failed after "
        f"{DIRECT_SETUP_ATTEMPTS} attempts; no email sent and state not updated. "
        f"Last error: {type(last_error).__name__}: {last_error}"
    )
    write_failure_artifact(message)
    raise DirectScraperRuntimeError(message)


def build_monitor_scrape_requests(monitors, mode=DAILY_MODE, backend=PLAYWRIGHT_BACKEND, extra_targets=()):
    requests = []
    for monitor in monitors:
        targets = list(monitor.targets)
        if extra_targets:
            targets.extend(extra_targets)

        categories = tuple(monitor.categories[mode])
        print(f"Monitor '{monitor.name}' categories for {mode}: {','.join(categories)}")
        if extra_targets:
            print(
                f"Monitor '{monitor.name}' temporary notify-only extra targets: "
                + ", ".join(f"{state}-{district}" for state, district in extra_targets)
            )

        for state_code, district in targets:
            query = ScrapeQuery(
                state_code=state_code,
                district=district,
                categories=categories,
                backend=backend,
            )
            requests.append(
                MonitorScrapeRequest(
                    monitor_name=monitor.name,
                    label=query.label,
                    query=query,
                )
            )
    return requests


def unique_scrape_queries(requests):
    queries = {}
    for request in requests:
        queries.setdefault(request.query, request.query)
    return list(queries.values())


def log_scrape_plan(monitors, enabled_monitors, requests, queries):
    print(f"Monitors loaded: {len(monitors)}")
    print(f"Monitors enabled: {len(enabled_monitors)}")
    print(f"Unique scrape queries: {len(queries)}")
    for query in queries:
        requested_by = sorted(
            {request.monitor_name for request in requests if request.query == query}
        )
        print(
            "  Query "
            f"{query.label} categories={','.join(query.categories)} "
            f"backend={query.backend} requested_by={','.join(requested_by)}"
        )


def execute_scrape_plan(
    queries,
    browser,
    backend=PLAYWRIGHT_BACKEND,
    direct_scraper=None,
    direct_index_html=None,
    deadline=None,
):
    results = {}
    errors = {}
    print(f"Actual scrapes performed: {len(queries)}")
    for query in queries:
        print(
            f"Scraping {query.label} "
            f"categories={','.join(query.categories)} backend={query.backend}..."
        )
        try:
            records = check_target_records(
                browser,
                direct_scraper,
                direct_index_html,
                query.state_code,
                query.district,
                backend=backend,
                categories=query.categories,
                deadline=deadline,
            )
            results[query] = records
            print(f"  Records extracted: {len(records)}")
        except Exception as e:
            if backend == DIRECT_WITH_RETRIES_BACKEND:
                raise
            errors[query] = (type(e).__name__, str(e))
            print(f"  Error after retries: {type(e).__name__}: {e}")
    return results, errors


def requests_for_monitor(requests, monitor_name):
    return [request for request in requests if request.monitor_name == monitor_name]


def check_target_records(
    browser,
    direct_scraper,
    direct_index_html,
    state_code,
    district,
    backend=PLAYWRIGHT_BACKEND,
    categories=("rare",),
    deadline=None,
):
    if backend in DIRECT_BACKENDS:
        try:
            ensure_time_remaining(deadline, f"{state_code}-{district}")
            started = time.perf_counter()
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
                f"categories={','.join(result.stats.categories)}, "
                f"runtime={time.perf_counter() - started:.2f}s"
            )
            return result.records
        except Exception as exc:
            if backend in {DIRECT_BACKEND, DIRECT_WITH_RETRIES_BACKEND}:
                message = (
                    f"Direct HTTP failed for {state_code}-{district}; "
                    "no email sent and state not updated. "
                    f"Error: {type(exc).__name__}: {exc}"
                )
                write_failure_artifact(message)
                raise DirectScraperRuntimeError(message) from exc
            print(f"  Direct HTTP failed; falling back to Playwright: {type(exc).__name__}: {exc}")

    return check_target_with_retry(
        browser,
        state_code,
        district,
        attempts=ATTEMPTS,
        wait_seconds=WAIT_SECONDS,
    )


def run_monitor_from_scraped(
    monitor,
    state,
    monitor_requests,
    scraped_results,
    scrape_errors,
    mode=DAILY_MODE,
    persist_state=True,
):
    all_results = []
    errors = []
    print(f"Fanout for monitor '{monitor.name}': {len(monitor_requests)} target requests")

    for request in monitor_requests:
        if request.query in scrape_errors:
            error_type, error_message = scrape_errors[request.query]
            errors.append((request.label, error_type, error_message))
            print(f"  {request.label}: fanout error {error_type}: {error_message}")
            continue

        records = scraped_results.get(request.query, [])
        all_results.append((request.label, records))
        print(f"  {request.label}: fanout records={len(records)}")

    new_results = compare_current_records(state, monitor.name, all_results)
    new_count = sum(len(records) for _, records in new_results)
    current_count = sum(len(records) for _, records in all_results)
    print(f"Records for monitor '{monitor.name}': {current_count}")
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
    deadline=None,
):
    requests = build_monitor_scrape_requests(
        [monitor],
        mode=mode,
        backend=backend,
        extra_targets=extra_targets,
    )
    queries = unique_scrape_queries(requests)
    results, errors = execute_scrape_plan(
        queries,
        browser,
        backend=backend,
        direct_scraper=direct_scraper,
        direct_index_html=direct_index_html,
        deadline=deadline,
    )
    return run_monitor_from_scraped(
        monitor,
        state,
        requests_for_monitor(requests, monitor.name),
        results,
        errors,
        mode=mode,
        persist_state=persist_state,
    )


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
    deadline = None
    if SCRAPER_BACKEND == DIRECT_WITH_RETRIES_BACKEND:
        deadline = time.monotonic() + DIRECT_TOTAL_TIMEOUT_SECONDS
        print(
            "Direct HTTP bounded runtime: "
            f"setup_attempts={DIRECT_SETUP_ATTEMPTS}, "
            f"request_timeout={DIRECT_HTTP_TIMEOUT_SECONDS}s, "
            f"backoff={DIRECT_RETRY_BACKOFF_SECONDS}s, "
            f"total_timeout={DIRECT_TOTAL_TIMEOUT_SECONDS}s"
        )

    monitor_requests = build_monitor_scrape_requests(
        enabled_monitors,
        mode=mode,
        backend=active_backend,
        extra_targets=NOTIFY_EXTRA_TARGETS if mode == NOTIFY_MODE else (),
    )
    scrape_queries = unique_scrape_queries(monitor_requests)
    log_scrape_plan(MONITORS, enabled_monitors, monitor_requests, scrape_queries)

    if SCRAPER_BACKEND in DIRECT_BACKENDS:
        direct_scraper = DirectOrnithoScraper(fetch_text=bounded_fetch_text(deadline))
        if SCRAPER_BACKEND == DIRECT_WITH_RETRIES_BACKEND:
            direct_index_html = fetch_direct_index_with_retries(direct_scraper, deadline=deadline)
        elif SCRAPER_BACKEND == DIRECT_BACKEND:
            direct_index_html = direct_scraper.fetch_text(CURRENT_OBSERVATIONS_URL)
        else:
            try:
                direct_index_html = direct_scraper.fetch_text(CURRENT_OBSERVATIONS_URL)
            except Exception as exc:
                active_backend = PLAYWRIGHT_BACKEND
                direct_scraper = None
                direct_index_html = None
                print(
                    "Direct HTTP setup failed; using Playwright fallback: "
                    f"{type(exc).__name__}: {exc}"
                )
                monitor_requests = build_monitor_scrape_requests(
                    enabled_monitors,
                    mode=mode,
                    backend=active_backend,
                    extra_targets=NOTIFY_EXTRA_TARGETS if mode == NOTIFY_MODE else (),
                )
                scrape_queries = unique_scrape_queries(monitor_requests)
                log_scrape_plan(MONITORS, enabled_monitors, monitor_requests, scrape_queries)

    if active_backend in {DIRECT_BACKEND, DIRECT_WITH_RETRIES_BACKEND}:
        scraped_results, scrape_errors = execute_scrape_plan(
            scrape_queries,
            None,
            backend=active_backend,
            direct_scraper=direct_scraper,
            direct_index_html=direct_index_html,
            deadline=deadline,
        )
        for monitor in enabled_monitors:
            state = run_monitor_from_scraped(
                monitor,
                state,
                requests_for_monitor(monitor_requests, monitor.name),
                scraped_results,
                scrape_errors,
                mode=mode,
                persist_state=not DRY_RUN,
            )
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)

        try:
            scraped_results, scrape_errors = execute_scrape_plan(
                scrape_queries,
                browser,
                backend=active_backend,
                direct_scraper=direct_scraper,
                direct_index_html=direct_index_html,
                deadline=deadline,
            )
            for monitor in enabled_monitors:
                state = run_monitor_from_scraped(
                    monitor,
                    state,
                    requests_for_monitor(monitor_requests, monitor.name),
                    scraped_results,
                    scrape_errors,
                    mode=mode,
                    persist_state=not DRY_RUN,
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
