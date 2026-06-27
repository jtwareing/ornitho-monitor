import time
import re

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from config import OUT
from ornitho.parser import parse_records

ORNITHO_URL = "https://www.ornitho.de/"
PAGE_TIMEOUT = 20000
NAVIGATION_TIMEOUT = 45000
INTERACTIVE_SELECTOR = "a, button, [role=button], [onclick]"


def safe_filename(text):
    return text.replace("*", "star").replace("/", "_")


def settle_page(page, timeout=10000):
    try:
        page.wait_for_load_state("domcontentloaded", timeout=timeout)
    except PlaywrightTimeoutError:
        pass

    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except PlaywrightTimeoutError:
        pass


def click_no_wait(page, locator, timeout=PAGE_TIMEOUT, settle_ms=1000):
    locator.wait_for(state="visible", timeout=timeout)
    locator.click(timeout=timeout, no_wait_after=True)
    settle_page(page)
    if settle_ms:
        page.wait_for_timeout(settle_ms)


def exact_text_pattern(text):
    return re.compile(rf"^\s*{re.escape(text)}\s*$")


def choose_below_reference(reference_box, candidate_boxes):
    if not reference_box:
        return None

    reference_y = reference_box["y"]
    below = [
        (index, box)
        for index, box in enumerate(candidate_boxes)
        if box and box["y"] > reference_y
    ]
    if not below:
        return None

    return min(below, key=lambda item: item[1]["y"])[0]


def district_locator(page, district, state_locator):
    candidates = page.locator(
        INTERACTIVE_SELECTOR,
        has_text=exact_text_pattern(district),
    )
    count = candidates.count()

    if count == 1:
        return candidates.first

    if count > 1:
        reference_box = state_locator.bounding_box(timeout=PAGE_TIMEOUT)
        candidate_boxes = [
            candidates.nth(index).bounding_box(timeout=PAGE_TIMEOUT)
            for index in range(count)
        ]
        index = choose_below_reference(reference_box, candidate_boxes)
        if index is not None:
            return candidates.nth(index)

    fallback = page.get_by_text(district, exact=True)
    if fallback.count() == 1:
        return fallback.first

    raise RuntimeError(f"Could not uniquely identify district selector for {district}")


def check_target(browser, state, district):
    context = browser.new_context()
    page = context.new_page()
    page.set_default_timeout(PAGE_TIMEOUT)
    page.set_default_navigation_timeout(NAVIGATION_TIMEOUT)

    try:
        page.goto(ORNITHO_URL, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT)
        settle_page(page)

        click_no_wait(page, page.get_by_role("emphasis").nth(1))
        click_no_wait(page, page.get_by_text("Current observations"), settle_ms=3000)

        state_locator = page.get_by_role("link", name=state, exact=True).first
        click_no_wait(page, state_locator)
        click_no_wait(page, district_locator(page, district, state_locator))
        click_no_wait(page, page.get_by_text("rare", exact=True), settle_ms=3000)

        page.wait_for_selector("body", state="attached", timeout=PAGE_TIMEOUT)

        html = page.content()
        text = BeautifulSoup(html, "lxml").get_text("\n", strip=True)

        label = f"{state}-{district}"
        file_label = safe_filename(label)
        OUT.joinpath(f"{file_label}_last_page.html").write_text(html, encoding="utf-8")
        OUT.joinpath(f"{file_label}_last_page_text.txt").write_text(text, encoding="utf-8")

        return parse_records(text)

    finally:
        context.close()


def check_target_with_retry(browser, state, district, attempts, wait_seconds):
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            if attempt > 1:
                print(f"  Waiting {wait_seconds} seconds before retry {attempt}...")
                time.sleep(wait_seconds)
                print(f"  Retry attempt {attempt}...")

            return check_target(browser, state, district)

        except Exception as e:
            last_error = e
            print(f"  Attempt {attempt} failed: {type(e).__name__}: {e}")

    raise last_error
