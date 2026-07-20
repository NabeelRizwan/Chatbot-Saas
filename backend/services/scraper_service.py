import re
import time

import httpx
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

REQUEST_HEADERS = {
    "User-Agent": (
        "ChatbotSaaSBot/2.0 "
        "(public website ingestion; +https://example.com/bot) "
        "Mozilla/5.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}
REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
RETRY_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_text_from_html(html: str) -> tuple[str | None, str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "header", "footer", "nav", "form", "button", "aside", "table", "figure", "sup"]):
        tag.decompose()
    for tag in soup.select(".infobox, .navbox, .metadata, .mw-editsection, .reference"):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else None
    main = (
        soup.find(id="mw-content-text")
        or soup.find("main")
        or soup.find("article")
        or soup.find(attrs={"role": "main"})
        or soup.body
        or soup
    )
    paragraphs = [
        clean_text(block.get_text(" ", strip=True))
        for block in main.find_all(["h1", "h2", "h3", "p"])
    ]
    if not paragraphs:
        paragraphs = [clean_text(block.get_text(" ", strip=True)) for block in main.find_all("li")]
    content = "\n\n".join(paragraph for paragraph in paragraphs if paragraph)
    if not content:
        content = clean_text(main.get_text(" "))
    return title, content


def _fetch_html(url: str) -> str:
    with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True, headers=REQUEST_HEADERS) as client:
        for attempt in range(3):
            try:
                response = client.get(url)
                if response.status_code not in RETRY_STATUS_CODES:
                    response.raise_for_status()
                    return response.text
                response.raise_for_status()
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                if attempt == 2 or (status_code is not None and status_code not in RETRY_STATUS_CODES):
                    raise
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError("Unable to fetch URL.")


def scrape_static_website(url: str) -> tuple[str | None, str]:
    return _extract_text_from_html(_fetch_html(url))


def scrape_dynamic_website(url: str) -> tuple[str | None, str]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)
        html = page.content()
        browser.close()
    return _extract_text_from_html(html)


def scrape_website(url: str, use_playwright: bool = False) -> tuple[str | None, str]:
    if use_playwright:
        return scrape_dynamic_website(url)
    return scrape_static_website(url)
