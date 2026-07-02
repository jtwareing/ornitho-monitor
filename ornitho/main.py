import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
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
    OPERATIONS_EMAIL,
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
OPERATIONS_ALERT_SUBJECT = "Ornitho Monitor Operational Alert"
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


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def new_run_summary(mode):
    return {
        "run_start_time": utc_now_iso(),
        "run_end_time": None,
        "total_runtime_seconds": None,
        "mode": mode,
        "backend": SCRAPER_BACKEND,
        "active_backend": SCRAPER_BACKEND,
        "dry_run": DRY_RUN,
        "monitors_loaded": len(MONITORS),
        "monitors_enabled": 0,
        "monitors_skipped": [],
        "unique_scrape_queries_planned": 0,
        "planned_scrape_queries": [],
        "actual_scrape_queries_executed": 0,
        "executed_scrape_queries": [],
        "scrape_setup_attempts": [],
        "direct_http": {
            "success": None,
            "failure_reason": None,
        },
        "records_per_monitor": {},
        "emails": {
            "user_sent": [],
            "user_skipped": [],
            "operations_alert_sent": False,
            "operations_alert_skipped_reason": None,
        },
        "state": {
            "saved": False,
            "skipped_reason": None,
        },
        "overall_run_status": "RUNNING",
        "failure_reason": None,
    }


def finish_run_summary(summary, started, status, failure_reason=None):
    summary["run_end_time"] = utc_now_iso()
    summary["total_runtime_seconds"] = round(time.perf_counter() - started, 2)
    summary["overall_run_status"] = status
    summary["failure_reason"] = failure_reason


def write_run_summary(summary):
    OUT.mkdir(exist_ok=True)
    OUT.joinpath("run_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def summary_query(query):
    return {
        "target": query.label,
        "categories": list(query.categories),
        "backend": query.backend,
    }


def build_operations_alert(summary, failure_reason):
    lines = [
        "Ornitho monitor operational alert",
        "",
        f"Status: FAILED",
        f"Mode: {summary['mode']}",
        f"Backend: {summary['active_backend']}",
        f"Dry run: {summary['dry_run']}",
        f"Started: {summary['run_start_time']}",
        f"Ended: {summary['run_end_time']}",
        f"Runtime seconds: {summary['total_runtime_seconds']}",
        "",
        "Failure reason:",
        str(failure_reason),
        "",
        f"Monitors loaded: {summary['monitors_loaded']}",
        f"Monitors enabled: {summary['monitors_enabled']}",
        f"Unique scrape queries planned: {summary['unique_scrape_queries_planned']}",
        f"Actual scrape queries executed: {summary['actual_scrape_queries_executed']}",
        "",
        "No user bird-notification emails were sent for this failed run.",
    ]
    return "\n".join(lines)


def send_operations_alert(summary, failure_reason):
    if not OPERATIONS_EMAIL:
        summary["emails"]["operations_alert_skipped_reason"] = "OPERATIONS_EMAIL not configured"
        print("OPERATIONS_EMAIL not configured; operational alert not sent.")
        return

    alert = build_operations_alert(summary, failure_reason)
    send_email(
        alert,
        dry_run=DRY_RUN,
        email_to=OPERATIONS_EMAIL,
        subject=OPERATIONS_ALERT_SUBJECT,
    )
    if DRY_RUN:
        summary["emails"]["operations_alert_skipped_reason"] = "DRY_RUN enabled"
        print("DRY_RUN enabled; operational alert email not sent.")
        return

    summary["emails"]["operations_alert_sent"] = True
    print("Operational alert email sent.")


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


def fetch_direct_index_with_retries(direct_scraper, deadline=None, summary=None):
    last_error = None
    for attempt in range(1, DIRECT_SETUP_ATTEMPTS + 1):
        ensure_time_remaining(deadline, "direct setup")
        started = time.perf_counter()
        attempt_summary = {
            "attempt": attempt,
            "success": False,
            "runtime_seconds": None,
            "error_type": None,
            "error_message": None,
        }
        try:
            print(f"Direct HTTP setup attempt {attempt}/{DIRECT_SETUP_ATTEMPTS}...")
            index_html = direct_scraper.fetch_text(CURRENT_OBSERVATIONS_URL)
            attempt_summary["success"] = True
            attempt_summary["runtime_seconds"] = round(time.perf_counter() - started, 2)
            if summary is not None:
                summary["scrape_setup_attempts"].append(attempt_summary)
                summary["direct_http"]["success"] = True
            print(f"Direct HTTP setup succeeded in {attempt_summary['runtime_seconds']:.2f}s.")
            return index_html
        except Exception as exc:
            last_error = exc
            attempt_summary["runtime_seconds"] = round(time.perf_counter() - started, 2)
            attempt_summary["error_type"] = type(exc).__name__
            attempt_summary["error_message"] = str(exc)
            if summary is not None:
                summary["scrape_setup_attempts"].append(attempt_summary)
            print(
                "Direct HTTP setup attempt "
                f"{attempt}/{DIRECT_SETUP_ATTEMPTS} failed after "
                f"{attempt_summary['runtime_seconds']:.2f}s: {type(exc).__name__}: {exc}"
            )
            if attempt < DIRECT_SETUP_ATTEMPTS:
                sleep_with_deadline(DIRECT_RETRY_BACKOFF_SECONDS, deadline)

    message = (
        "Direct HTTP setup failed after "
        f"{DIRECT_SETUP_ATTEMPTS} attempts; no email sent and state not updated. "
        f"Last error: {type(last_error).__name__}: {last_error}"
    )
    if summary is not None:
        summary["direct_http"]["success"] = False
        summary["direct_http"]["failure_reason"] = message
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


def record_scrape_plan(summary, active_backend, enabled_monitors, skipped_monitors, queries):
    if summary is None:
        return
    summary["active_backend"] = active_backend
    summary["monitors_enabled"] = len(enabled_monitors)
    summary["monitors_skipped"] = [monitor.name for monitor in skipped_monitors]
    summary["unique_scrape_queries_planned"] = len(queries)
    summary["planned_scrape_queries"] = [summary_query(query) for query in queries]


def execute_scrape_plan(
    queries,
    browser,
    backend=PLAYWRIGHT_BACKEND,
    direct_scraper=None,
    direct_index_html=None,
    deadline=None,
    summary=None,
):
    results = {}
    errors = {}
    print(f"Actual scrapes performed: {len(queries)}")
    for query in queries:
        if summary is not None:
            summary["actual_scrape_queries_executed"] += 1
            summary["executed_scrape_queries"].append(summary_query(query))
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
    summary=None,
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
    if summary is not None:
        summary["records_per_monitor"][monitor.name] = {
            "current_records": current_count,
            "new_records": new_count,
            "targets": {label: len(records) for label, records in all_results},
            "errors": [
                {"target": label, "type": error_type, "message": message}
                for label, error_type, message in errors
            ],
        }

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
        if summary is not None:
            if DRY_RUN:
                summary["emails"]["user_skipped"].append(
                    {"monitor": monitor.name, "reason": "DRY_RUN enabled"}
                )
            else:
                summary["emails"]["user_sent"].append(monitor.name)
        if not DRY_RUN:
            print("Email sent.")
    else:
        if summary is not None:
            summary["emails"]["user_skipped"].append(
                {"monitor": monitor.name, "reason": "no new records"}
            )
        print(f"No new records for monitor '{monitor.name}'; notification email not sent.")

    if persist_state:
        save_state(updated_state, STATE_PATH)
        if summary is not None:
            summary["state"]["saved"] = True
            summary["state"]["skipped_reason"] = None
        print(f"State saved to {STATE_PATH}.")
        return updated_state

    if summary is not None:
        summary["state"]["skipped_reason"] = "DRY_RUN enabled"
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
        summary=None,
    )


def run(mode=DAILY_MODE):
    run_started = time.perf_counter()
    summary = new_run_summary(mode)
    if SCRAPER_BACKEND not in SCRAPER_BACKENDS:
        failure_reason = f"Unsupported SCRAPER_BACKEND: {SCRAPER_BACKEND}"
        finish_run_summary(summary, run_started, "FAILED", failure_reason)
        write_run_summary(summary)
        raise RuntimeError(failure_reason)

    try:
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
        skipped_monitors = []
        for monitor in MONITORS:
            if monitor.enabled:
                enabled_monitors.append(monitor)
            else:
                skipped_monitors.append(monitor)
                print(f"Monitor '{monitor.name}' disabled; skipping.")
        if not enabled_monitors:
            print("No enabled monitors; nothing to do.")
            summary["monitors_enabled"] = 0
            summary["monitors_skipped"] = [monitor.name for monitor in skipped_monitors]
            summary["state"]["skipped_reason"] = "no enabled monitors"
            finish_run_summary(summary, run_started, "SUCCESS")
            write_run_summary(summary)
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
        record_scrape_plan(summary, active_backend, enabled_monitors, skipped_monitors, scrape_queries)

        if SCRAPER_BACKEND in DIRECT_BACKENDS:
            direct_scraper = DirectOrnithoScraper(fetch_text=bounded_fetch_text(deadline))
            if SCRAPER_BACKEND == DIRECT_WITH_RETRIES_BACKEND:
                direct_index_html = fetch_direct_index_with_retries(
                    direct_scraper,
                    deadline=deadline,
                    summary=summary,
                )
            elif SCRAPER_BACKEND == DIRECT_BACKEND:
                direct_index_html = direct_scraper.fetch_text(CURRENT_OBSERVATIONS_URL)
                summary["direct_http"]["success"] = True
            else:
                try:
                    direct_index_html = direct_scraper.fetch_text(CURRENT_OBSERVATIONS_URL)
                    summary["direct_http"]["success"] = True
                except Exception as exc:
                    active_backend = PLAYWRIGHT_BACKEND
                    direct_scraper = None
                    direct_index_html = None
                    summary["direct_http"]["success"] = False
                    summary["direct_http"]["failure_reason"] = f"{type(exc).__name__}: {exc}"
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
                    record_scrape_plan(
                        summary,
                        active_backend,
                        enabled_monitors,
                        skipped_monitors,
                        scrape_queries,
                    )

        if active_backend in {DIRECT_BACKEND, DIRECT_WITH_RETRIES_BACKEND}:
            scraped_results, scrape_errors = execute_scrape_plan(
                scrape_queries,
                None,
                backend=active_backend,
                direct_scraper=direct_scraper,
                direct_index_html=direct_index_html,
                deadline=deadline,
                summary=summary,
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
                    summary=summary,
                )
            finish_run_summary(summary, run_started, "SUCCESS")
            write_run_summary(summary)
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
                    summary=summary,
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
                        summary=summary,
                    )
            finally:
                browser.close()

        finish_run_summary(summary, run_started, "SUCCESS")
        write_run_summary(summary)
    except Exception as exc:
        failure_reason = f"{type(exc).__name__}: {exc}"
        if not summary["state"]["saved"]:
            summary["state"]["skipped_reason"] = "run failed"
        finish_run_summary(summary, run_started, "FAILED", failure_reason)
        try:
            send_operations_alert(summary, failure_reason)
        except Exception as alert_exc:
            summary["emails"]["operations_alert_skipped_reason"] = (
                f"operational alert failed: {type(alert_exc).__name__}: {alert_exc}"
            )
            print(
                "Operational alert failed: "
                f"{type(alert_exc).__name__}: {alert_exc}"
            )
        finally:
            write_run_summary(summary)
        raise


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
