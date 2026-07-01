from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import html
import json
import re
import time
from typing import Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

ORNITHO_BASE_URL = "https://www.ornitho.de/"
CURRENT_OBSERVATIONS_URL = (
    "https://www.ornitho.de/index.php?m_id=5"
    "&p_c=duration&p_cc=-&sp_tg=1&sp_DChoice=offset&sp_DOffset=2"
    "&sp_SChoice=category"
    "&sp_Cat[never]=1&sp_Cat[veryrare]=1&sp_Cat[rare]=1"
    "&sp_Cat[unusual]=1&sp_Cat[escaped]=1&sp_Cat[common]=1&sp_Cat[verycommon]=1"
    "&sp_FChoice=list&sp_FGraphFormat=auto&sp_FMapFormat=none"
    "&sp_FDisplay=DATE_PLACE_SPECIES&sp_FOrder=ALPHA&sp_FOrderListSpecies=ALPHA"
    "&sp_FListSpeciesChoice=DATA&sp_FOrderSynth=ALPHA&sp_FGraphChoice=DATA"
    "&sp_DFormat=DESC&sp_FAltScale=250&sp_FAltChoice=DATA&sp_FExportFormat=XLS"
    "&langu=en"
)
DEFAULT_CATEGORIES = ("rare",)
CATEGORY_KEYS = ("never", "veryrare", "rare", "unusual", "escaped", "common", "verycommon")
CONTROL_URL_RE = re.compile(r"'([^']*index\.php\?m_id=5[^']*)'")
OBSERVATION_REQUEST_RE = re.compile(r"index\.php\?m_id=1351[^\"']*content=observations_by_page[^\"']*")


@dataclass(frozen=True)
class TargetControl:
    target: tuple[str, str]
    code: str
    title: str
    document_url: str
    order: int


@dataclass
class DirectScrapeStats:
    request_count: int = 0
    pages_fetched: int = 0
    records_parsed: int = 0
    runtime_seconds: float = 0.0
    targets: dict[str, dict[str, object]] = field(default_factory=dict)
    categories: tuple[str, ...] = DEFAULT_CATEGORIES


@dataclass
class DirectScrapeResult:
    records: list[dict[str, str]]
    stats: DirectScrapeStats


class TargetResolutionError(RuntimeError):
    pass


def default_fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8")


def extract_control_urls(onclick: str) -> list[str]:
    return [html.unescape(match) for match in CONTROL_URL_RE.findall(onclick or "")]


def query_value(url: str, key: str) -> str | None:
    return dict(parse_qsl(urlsplit(url).query, keep_blank_values=True)).get(key)


def is_district_url(url: str) -> bool:
    sp_cc = query_value(url, "sp_cC") or ""
    return "sp_SChoice=category" in url and sp_cc.startswith("-")


def choose_selected_url(urls: Iterable[str]) -> str:
    candidates = [url for url in urls if is_district_url(url)]
    if not candidates:
        raise TargetResolutionError("No district-level Ornitho URL found for target control")

    # buildUrl controls provide the exact single-district URL first; the second
    # URL is a toggle variant and can broaden the query when all districts are active.
    return candidates[0]


def find_target_control(html_text: str, target: tuple[str, str]) -> TargetControl:
    state, district = target
    soup = BeautifulSoup(html_text, "lxml")
    candidates = []

    for order, element in enumerate(soup.find_all(attrs={"onclick": True})):
        text = element.get_text(" ", strip=True)
        if text != district:
            continue

        urls = extract_control_urls(element.get("onclick", ""))
        district_urls = [url for url in urls if is_district_url(url)]
        if not district_urls:
            continue

        candidates.append(
            TargetControl(
                target=target,
                code=district,
                title=element.get("title") or "",
                document_url=urljoin(ORNITHO_BASE_URL, choose_selected_url(urls)),
                order=order,
            )
        )

    if len(candidates) == 1:
        return candidates[0]

    if not candidates:
        raise TargetResolutionError(f"Could not resolve district-level control for {state}-{district}")

    title_matches = [
        candidate for candidate in candidates if candidate.title.upper().startswith(district.upper())
    ]
    if len(title_matches) == 1:
        return title_matches[0]

    titles = ", ".join(candidate.title or "<untitled>" for candidate in candidates)
    raise TargetResolutionError(f"Ambiguous district-level controls for {state}-{district}: {titles}")


def apply_categories(url: str, categories: Iterable[str]) -> str:
    selected = set(categories)
    unknown = selected.difference(CATEGORY_KEYS)
    if unknown:
        raise ValueError(f"Unsupported Ornitho categories: {', '.join(sorted(unknown))}")

    return update_query(
        url,
        {f"sp_Cat[{category}]": "1" if category in selected else "0" for category in CATEGORY_KEYS},
    )


def update_query(url: str, updates: dict[str, str]) -> str:
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    filtered = [(key, value) for key, value in query if key not in updates]
    filtered.extend(updates.items())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(filtered), parts.fragment))


def observation_page_url(document_url: str, page_number: int) -> str:
    return update_query(
        document_url,
        {
            "m_id": "1351",
            "content": "observations_by_page",
            "backlink": "skip",
            "mp_current_page": str(page_number),
            "txid": str(page_number),
            "langu": "en",
        },
    )


def ordinal(day: int) -> str:
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def format_date(raw_date: str, fallback: str = "") -> str:
    if raw_date:
        dt = datetime.fromisoformat(raw_date)
        return f"{dt:%A}, {dt:%B} {ordinal(dt.day)}, {dt:%Y}"
    return fallback


def clean_text(value: object) -> str:
    if not value:
        return ""
    return BeautifulSoup(str(value), "lxml").get_text(" ", strip=True)


def detail_from_row(row: dict) -> str:
    details = []
    for key in ("remarks", "remarks_hidden"):
        for remark in row.get(key) or []:
            title = clean_text(remark.get("title", ""))
            content = clean_text(remark.get("content", ""))
            text = " ".join(part for part in (title, content) if part).strip()
            if text:
                details.append(text)
    return " | ".join(details)


def row_to_record(row: dict) -> dict[str, str]:
    species = row.get("species_array") or {}
    fallback_date = clean_text((row.get("listTop") or {}).get("title", ""))
    return {
        "date": format_date(row.get("date_raw", ""), fallback=fallback_date),
        "location": clean_text((row.get("listSubmenu") or {}).get("title", "")),
        "count": clean_text(row.get("birds_count_raw") or row.get("birds_count") or ""),
        "species": clean_text(row.get("sighting_detail_short_raw") or species.get("name") or ""),
        "scientific": clean_text(species.get("latin_name", "")),
        "detail": detail_from_row(row),
        "rarity": clean_text(species.get("rarity", "")),
    }


def extract_observation_request_url(html_text: str) -> str | None:
    match = OBSERVATION_REQUEST_RE.search(html.unescape(html_text))
    if not match:
        return None
    return urljoin(ORNITHO_BASE_URL, match.group(0))


class DirectOrnithoScraper:
    def __init__(self, fetch_text: Callable[[str], str] = default_fetch_text):
        self.fetch_text = fetch_text

    def fetch_records_for_document_url(
        self,
        document_url: str,
        categories: Iterable[str] = DEFAULT_CATEGORIES,
        max_pages: int = 50,
    ) -> DirectScrapeResult:
        stats = DirectScrapeStats(categories=tuple(categories))
        started = time.perf_counter()
        records: list[dict[str, str]] = []
        filtered_url = apply_categories(document_url, stats.categories)

        try:
            for page_number in range(1, max_pages + 1):
                page_url = observation_page_url(filtered_url, page_number)
                payload = json.loads(self.fetch_text(page_url))
                stats.request_count += 1
                stats.pages_fetched += 1

                rows = payload.get("data") or []
                records.extend(row_to_record(row) for row in rows)

                if payload.get("data_is_finished") or not rows:
                    break
            else:
                raise RuntimeError(f"Ornitho JSON pagination exceeded {max_pages} pages")

            stats.records_parsed = len(records)
            return DirectScrapeResult(records=records, stats=stats)
        finally:
            stats.runtime_seconds = time.perf_counter() - started

    def check_target(
        self,
        target: tuple[str, str],
        index_html: str | None = None,
        categories: Iterable[str] = DEFAULT_CATEGORIES,
    ) -> DirectScrapeResult:
        started = time.perf_counter()
        stats = DirectScrapeStats(categories=tuple(categories))

        if index_html is None:
            index_html = self.fetch_text(CURRENT_OBSERVATIONS_URL)
            stats.request_count += 1

        control = find_target_control(index_html, target)
        result = self.fetch_records_for_document_url(control.document_url, categories=stats.categories)
        label = f"{target[0]}-{target[1]}"

        result.stats.request_count += stats.request_count
        result.stats.runtime_seconds += time.perf_counter() - started
        result.stats.targets[label] = {
            "control_title": control.title,
            "pages_fetched": result.stats.pages_fetched,
            "records_parsed": len(result.records),
            "categories": list(result.stats.categories),
        }
        return result


def check_target_direct(state: str, district: str) -> list[dict[str, str]]:
    return DirectOrnithoScraper().check_target((state, district)).records
