from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from config import TARGETS
from ornitho.direct_scraper import CURRENT_OBSERVATIONS_URL, DirectOrnithoScraper
from ornitho.scraper import check_target_with_retry

COMPARISON_FIELDS = ("species", "count", "date", "location", "scientific", "detail", "rarity")


def record_key(record: dict[str, str]) -> tuple[str, str, str, str, str, str]:
    return (
        record.get("species", ""),
        record.get("count", ""),
        record.get("date", ""),
        record.get("location", ""),
        record.get("scientific", ""),
        record.get("detail", ""),
    )


def normalize_playwright_record(record: dict[str, str]) -> dict[str, str]:
    normalized = {field: record.get(field, "") for field in COMPARISON_FIELDS}
    normalized["rarity"] = ""
    return normalized


def normalize_direct_record(record: dict[str, str]) -> dict[str, str]:
    return {field: record.get(field, "") for field in COMPARISON_FIELDS}


def compare_target(playwright_records: list[dict[str, str]], direct_records: list[dict[str, str]]) -> dict[str, object]:
    playwright_by_key = {record_key(record): record for record in playwright_records}
    direct_by_key = {record_key(record): record for record in direct_records}
    playwright_keys = set(playwright_by_key)
    direct_keys = set(direct_by_key)

    matched_keys = sorted(playwright_keys & direct_keys)
    rarity_compared = any(direct_by_key[key].get("rarity") for key in matched_keys)

    return {
        "matches": playwright_keys == direct_keys,
        "playwright_count": len(playwright_records),
        "direct_count": len(direct_records),
        "matched_count": len(matched_keys),
        "missing_from_direct": [playwright_by_key[key] for key in sorted(playwright_keys - direct_keys)],
        "extra_in_direct": [direct_by_key[key] for key in sorted(direct_keys - playwright_keys)],
        "rarity_category": {
            "playwright_available": False,
            "direct_available": any(record.get("rarity") for record in direct_records),
            "compared": rarity_compared,
        },
    }


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_text_report(path: Path, comparison: dict[str, object], summary: dict[str, object]) -> None:
    lines = [
        "Ornitho Direct Shadow Compare",
        "",
        f"Targets: {summary['targets']}",
        f"Categories: {', '.join(summary['categories'])}",
        f"Playwright attempts per target: {summary['playwright_attempts']}",
        f"Playwright wait seconds: {summary['playwright_wait_seconds']}",
        f"Playwright headless: {summary['playwright_headless']}",
        f"Playwright runtime seconds: {summary['playwright_runtime_seconds']:.2f}",
        f"Direct runtime seconds: {summary['direct_runtime_seconds']:.2f}",
        f"Direct requests: {summary['direct_request_count']}",
        f"Direct pages fetched: {summary['direct_pages_fetched']}",
        f"Direct records parsed: {summary['direct_records_parsed']}",
        "",
    ]

    for label, result in comparison.items():
        status = "MATCH" if result.get("matches") else "DIFF"
        if result.get("playwright_error") or result.get("direct_error"):
            status = "ERROR"
        lines.append(
            f"{label}: {status} "
            f"playwright={result.get('playwright_count', 0)} direct={result.get('direct_count', 0)} "
            f"matched={result.get('matched_count', 0)}"
        )
        if result.get("playwright_error"):
            lines.append(f"  Playwright error: {result['playwright_error']}")
        if result.get("direct_error"):
            lines.append(f"  Direct error: {result['direct_error']}")
        rarity = result.get("rarity_category") or {}
        lines.append(
            "  Rarity category: "
            f"playwright_available={rarity.get('playwright_available', False)} "
            f"direct_available={rarity.get('direct_available', False)} "
            f"compared={rarity.get('compared', False)}"
        )
        if result.get("missing_from_direct"):
            lines.append(f"  Missing from direct: {len(result['missing_from_direct'])}")
        if result.get("extra_in_direct"):
            lines.append(f"  Extra in direct: {len(result['extra_in_direct'])}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_shadow_compare(
    output_dir: Path,
    categories: tuple[str, ...],
    playwright_attempts: int = 2,
    playwright_wait_seconds: int = 5,
    playwright_headless: bool = False,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    labels = [f"{state}-{district}" for state, district in TARGETS]

    playwright_results: dict[str, object] = {}
    playwright_started = time.perf_counter()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=playwright_headless)
        try:
            for state, district in TARGETS:
                label = f"{state}-{district}"
                print(f"Playwright shadow check: {label}", flush=True)
                started = time.perf_counter()
                try:
                    records = check_target_with_retry(
                        browser,
                        state,
                        district,
                        attempts=playwright_attempts,
                        wait_seconds=playwright_wait_seconds,
                    )
                    playwright_results[label] = {
                        "records": [normalize_playwright_record(record) for record in records],
                        "runtime_seconds": time.perf_counter() - started,
                        "error": None,
                    }
                except Exception as exc:
                    playwright_results[label] = {
                        "records": [],
                        "runtime_seconds": time.perf_counter() - started,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
        finally:
            browser.close()
    playwright_runtime = time.perf_counter() - playwright_started

    direct_results: dict[str, object] = {}
    direct_started = time.perf_counter()
    scraper = DirectOrnithoScraper()
    index_html = scraper.fetch_text(CURRENT_OBSERVATIONS_URL)
    direct_request_count = 1
    direct_pages_fetched = 0
    direct_records_parsed = 0

    for state, district in TARGETS:
        label = f"{state}-{district}"
        print(f"Direct HTTP shadow check: {label}", flush=True)
        started = time.perf_counter()
        try:
            result = scraper.check_target((state, district), index_html=index_html, categories=categories)
            direct_request_count += result.stats.request_count
            direct_pages_fetched += result.stats.pages_fetched
            direct_records_parsed += result.stats.records_parsed
            direct_results[label] = {
                "records": [normalize_direct_record(record) for record in result.records],
                "runtime_seconds": time.perf_counter() - started,
                "stats": result.stats.__dict__,
                "error": None,
            }
        except Exception as exc:
            direct_results[label] = {
                "records": [],
                "runtime_seconds": time.perf_counter() - started,
                "stats": {},
                "error": f"{type(exc).__name__}: {exc}",
            }

    direct_runtime = time.perf_counter() - direct_started

    comparison: dict[str, object] = {}
    for label in labels:
        playwright_error = playwright_results[label]["error"]
        direct_error = direct_results[label]["error"]
        if playwright_error or direct_error:
            comparison[label] = {
                "matches": False,
                "playwright_count": len(playwright_results[label]["records"]),
                "direct_count": len(direct_results[label]["records"]),
                "matched_count": 0,
                "missing_from_direct": [],
                "extra_in_direct": [],
                "playwright_error": playwright_error,
                "direct_error": direct_error,
                "rarity_category": {
                    "playwright_available": False,
                    "direct_available": any(record.get("rarity") for record in direct_results[label]["records"]),
                    "compared": False,
                },
            }
        else:
            comparison[label] = compare_target(
                playwright_results[label]["records"],
                direct_results[label]["records"],
            )

    summary = {
        "targets": labels,
        "categories": list(categories),
        "playwright_attempts": playwright_attempts,
        "playwright_wait_seconds": playwright_wait_seconds,
        "playwright_headless": playwright_headless,
        "playwright_runtime_seconds": playwright_runtime,
        "direct_runtime_seconds": direct_runtime,
        "direct_request_count": direct_request_count,
        "direct_pages_fetched": direct_pages_fetched,
        "direct_records_parsed": direct_records_parsed,
        "all_targets_match": all(result.get("matches") for result in comparison.values()),
        "targets_with_errors": [
            label
            for label, result in comparison.items()
            if result.get("playwright_error") or result.get("direct_error")
        ],
    }

    write_json(output_dir / "playwright_output.json", playwright_results)
    write_json(output_dir / "direct_http_output.json", direct_results)
    write_json(output_dir / "comparison_report.json", {"summary": summary, "targets": comparison})
    write_text_report(output_dir / "comparison_report.txt", comparison, summary)
    return {"summary": summary, "targets": comparison}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Playwright and direct HTTP Ornitho scrapers side by side.")
    parser.add_argument("--output-dir", default="output/direct-shadow-compare")
    parser.add_argument(
        "--categories",
        default="rare",
        help="Comma-separated Ornitho category filters for the direct HTTP scraper.",
    )
    parser.add_argument("--playwright-attempts", type=int, default=2)
    parser.add_argument("--playwright-wait-seconds", type=int, default=5)
    parser.add_argument("--playwright-headless", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    categories = tuple(category.strip() for category in args.categories.split(",") if category.strip())
    result = run_shadow_compare(
        Path(args.output_dir),
        categories,
        playwright_attempts=args.playwright_attempts,
        playwright_wait_seconds=args.playwright_wait_seconds,
        playwright_headless=args.playwright_headless,
    )
    print(json.dumps(result["summary"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
