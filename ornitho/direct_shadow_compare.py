from __future__ import annotations

import argparse
import json
from pathlib import Path

from config import TARGETS
from ornitho.direct_scraper import DirectOrnithoScraper, extract_observation_request_url
from ornitho.parser import parse_records


def safe_filename(label: str) -> str:
    return label.replace("*", "star").replace("/", "_")


def record_key(record: dict[str, str]) -> tuple[str, str, str, str, str]:
    return (
        record.get("date", ""),
        record.get("location", ""),
        record.get("species", ""),
        record.get("scientific", ""),
        record.get("count", ""),
    )


def compare_records(expected: list[dict[str, str]], actual: list[dict[str, str]]) -> dict[str, object]:
    expected_keys = {record_key(record) for record in expected}
    actual_keys = {record_key(record) for record in actual}
    return {
        "expected_count": len(expected),
        "actual_count": len(actual),
        "missing": [list(item) for item in sorted(expected_keys - actual_keys)],
        "extra": [list(item) for item in sorted(actual_keys - expected_keys)],
        "matches": expected_keys == actual_keys,
    }


def compare_artifact_target(artifact_dir: Path, label: str) -> dict[str, object]:
    file_label = safe_filename(label)
    html_path = artifact_dir / f"{file_label}_last_page.html"
    text_path = artifact_dir / f"{file_label}_last_page_text.txt"

    expected = parse_records(text_path.read_text(encoding="utf-8"))
    html = html_path.read_text(encoding="utf-8")
    request_url = extract_observation_request_url(html)
    if request_url is None:
        raise RuntimeError(f"No Ornitho observation request found in {html_path}")

    scraper = DirectOrnithoScraper()
    actual_result = scraper.fetch_records_for_document_url(request_url)
    comparison = compare_records(expected, actual_result.records)
    comparison["stats"] = actual_result.stats.__dict__
    return comparison


def compare_artifacts(artifact_dir: Path, targets=TARGETS) -> dict[str, object]:
    results = {}
    for state, district in targets:
        label = f"{state}-{district}"
        results[label] = compare_artifact_target(artifact_dir, label)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Shadow-compare direct Ornitho JSON scraping with saved artifacts.")
    parser.add_argument("--artifact-dir", default="output", help="Directory containing *_last_page.html/text artifacts.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a short text summary.")
    args = parser.parse_args()

    results = compare_artifacts(Path(args.artifact_dir))
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return

    for label, result in results.items():
        status = "MATCH" if result["matches"] else "DIFF"
        print(f"{label}: {status} expected={result['expected_count']} actual={result['actual_count']}")
        stats = result["stats"]
        print(
            f"  requests={stats['request_count']} pages={stats['pages_fetched']} "
            f"records={stats['records_parsed']} runtime={stats['runtime_seconds']:.2f}s"
        )


if __name__ == "__main__":
    main()
