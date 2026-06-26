from bs4 import BeautifulSoup

from config import OUT
from ornitho.parser import parse_records


def safe_filename(text):
    return text.replace("*", "star").replace("/", "_")


def click_no_wait(locator, timeout=15000):
    locator.click(timeout=timeout, no_wait_after=True)


def check_target(browser, state, district):
    page = browser.new_page()
    page.set_default_timeout(15000)

    try:
        page.goto("https://www.ornitho.de/", wait_until="domcontentloaded", timeout=30000)
        click_no_wait(page.get_by_role("emphasis").nth(1))
        page.wait_for_timeout(1000)

        click_no_wait(page.get_by_text("Current observations"))
        page.wait_for_timeout(5000)

        click_no_wait(page.get_by_role("link", name=state, exact=True))
        page.wait_for_timeout(2000)

        click_no_wait(page.get_by_text(district, exact=True))
        page.wait_for_timeout(2000)

        click_no_wait(page.get_by_text("rare", exact=True))
        page.wait_for_timeout(5000)

        html = page.content()
        text = BeautifulSoup(html, "lxml").get_text("\n", strip=True)

        label = f"{state}-{district}"
        file_label = safe_filename(label)
        OUT.joinpath(f"{file_label}_last_page.html").write_text(html, encoding="utf-8")
        OUT.joinpath(f"{file_label}_last_page_text.txt").write_text(text, encoding="utf-8")

        return parse_records(text)

    finally:
        page.close()


def check_target_with_retry(browser, state, district, attempts, wait_seconds):
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            if attempt > 1:
                print(f"  Waiting {wait_seconds} seconds before retry {attempt}...")
                wait_page = browser.new_page()
                wait_page.wait_for_timeout(wait_seconds * 1000)
                wait_page.close()
                print(f"  Retry attempt {attempt}...")

            return check_target(browser, state, district)

        except Exception as e:
            last_error = e
            print(f"  Attempt {attempt} failed: {type(e).__name__}: {e}")

    raise last_error