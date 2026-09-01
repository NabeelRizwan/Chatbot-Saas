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


import json


def clean_text(text: str) -> str:
    """Normalize excessive whitespace while preserving paragraph/newline structures."""
    if not text:
        return ""
    # Normalize spaces/tabs on lines
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    # Remove excessive blank lines (>2)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _table_to_markdown(table_tag) -> str:
    """Converts an HTML table into a clean Markdown table with key-value row representations."""
    rows = table_tag.find_all("tr")
    if not rows:
        return ""

    matrix = []
    for row in rows:
        cols = [re.sub(r"\s+", " ", cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
        if cols and any(c for c in cols):
            matrix.append(cols)

    if not matrix:
        return ""

    num_cols = max(len(r) for r in matrix)
    for r in matrix:
        while len(r) < num_cols:
            r.append("")

    lines = []
    headers = matrix[0]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * num_cols) + " |")
    for row in matrix[1:]:
        lines.append("| " + " | ".join(row) + " |")

    # Also append row-by-row key-value summary for spec tables
    if len(headers) > 1 and len(matrix) > 1:
        summary_lines = []
        for row in matrix[1:]:
            row_title = row[0]
            if row_title:
                row_specs = [
                    f"{headers[i]}: {row[i]}"
                    for i in range(1, min(len(row), len(headers)))
                    if row[i]
                ]
                if row_specs:
                    summary_lines.append(f"- {row_title} ({', '.join(row_specs)})")
        if summary_lines:
            lines.append("\n" + "\n".join(summary_lines))

    return "\n".join(lines)


def _extract_json_ld(soup: BeautifulSoup) -> list[str]:
    """Extracts JSON-LD structured data (Product, Offer, FAQPage, Organization, Service)."""
    structured = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            raw = script.string or script.get_text()
            if not raw:
                continue
            data = json.loads(raw.strip())
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                if "@graph" in item and isinstance(item["@graph"], list):
                    items.extend(item["@graph"])
                    continue

                type_name = item.get("@type", "")
                if not type_name:
                    continue

                if type_name in ("Product", "IndividualProduct", "ProductModel"):
                    name = item.get("name", "")
                    desc = item.get("description", "")
                    brand = item.get("brand", {}).get("name", "") if isinstance(item.get("brand"), dict) else item.get("brand", "")
                    sku = item.get("sku", "") or item.get("productID", "") or item.get("mpn", "")
                    offers = item.get("offers", {})
                    price = ""
                    currency = ""
                    if isinstance(offers, dict):
                        price = str(offers.get("price", ""))
                        currency = str(offers.get("priceCurrency", ""))
                    elif isinstance(offers, list) and offers:
                        price = str(offers[0].get("price", ""))
                        currency = str(offers[0].get("priceCurrency", ""))

                    prod_lines = [f"### Structured Product: {name}"]
                    if brand:
                        prod_lines.append(f"- Brand: {brand}")
                    if sku:
                        prod_lines.append(f"- SKU / Model: {sku}")
                    if price:
                        prod_lines.append(f"- Price: {currency} {price}".strip())
                    if desc:
                        prod_lines.append(f"- Description: {desc}")
                    structured.append("\n".join(prod_lines))

                elif type_name in ("FAQPage", "QAPage"):
                    main_entities = item.get("mainEntity", [])
                    if isinstance(main_entities, list):
                        faq_lines = ["### Frequently Asked Questions"]
                        for qa in main_entities:
                            q = qa.get("name", "") or qa.get("question", "")
                            ans = qa.get("acceptedAnswer", {}).get("text", "") if isinstance(qa.get("acceptedAnswer"), dict) else ""
                            if q and ans:
                                clean_ans = re.sub(r"<[^>]+>", " ", ans).strip()
                                faq_lines.append(f"**Q: {q}**\nA: {clean_ans}\n")
                        if len(faq_lines) > 1:
                            structured.append("\n".join(faq_lines))
        except Exception:
            continue
    return structured


def _extract_text_from_html(html: str) -> tuple[str | None, str]:
    soup = BeautifulSoup(html, "html.parser")

    # Extract JSON-LD structured schemas before decomposing scripts
    json_ld_sections = _extract_json_ld(soup)

    # Decompose purely non-content interactive/style elements
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form", "button", "input", "select"]):
        tag.decompose()
    for tag in soup.select(".mw-editsection, .reference"):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else None

    # Meta description & OpenGraph description
    meta_desc = ""
    meta_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if meta_tag and meta_tag.get("content"):
        meta_desc = f"**Page Description**: {meta_tag['content'].strip()}"

    main = (
        soup.find(id="mw-content-text")
        or soup.find("main")
        or soup.find("article")
        or soup.find(attrs={"role": "main"})
        or soup.body
        or soup
    )

    blocks = []
    if meta_desc:
        blocks.append(meta_desc)

    # Walk main content DOM elements preserving hierarchy, tables, lists, accordions
    for elem in main.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "table", "details", "dl", "ul", "ol"]):
        tag_name = elem.name.lower()

        if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag_name[1])
            heading_text = elem.get_text(" ", strip=True)
            if heading_text:
                blocks.append(f"{'#' * level} {heading_text}")

        elif tag_name == "table":
            md_table = _table_to_markdown(elem)
            if md_table:
                blocks.append(md_table)

        elif tag_name == "details":
            summary = elem.find("summary")
            summary_text = summary.get_text(" ", strip=True) if summary else "FAQ"
            # Get body text excluding summary
            details_body = elem.get_text(" ", strip=True)
            if summary and summary_text in details_body:
                details_body = details_body.replace(summary_text, "", 1).strip()
            if summary_text and details_body:
                blocks.append(f"### Q: {summary_text}\nA: {details_body}")

        elif tag_name == "dl":
            dl_lines = []
            for dt in elem.find_all("dt"):
                dd = dt.find_next_sibling("dd")
                dt_text = dt.get_text(" ", strip=True)
                dd_text = dd.get_text(" ", strip=True) if dd else ""
                if dt_text:
                    dl_lines.append(f"- {dt_text}: {dd_text}".strip())
            if dl_lines:
                blocks.append("\n".join(dl_lines))

        elif tag_name in ("ul", "ol"):
            # Only process top-level lists not nested inside another already processed list
            if elem.parent and elem.parent.name in ("ul", "ol", "li"):
                continue
            list_items = []
            for idx, li in enumerate(elem.find_all("li", recursive=False), start=1):
                li_text = li.get_text(" ", strip=True)
                if li_text:
                    prefix = f"{idx}. " if tag_name == "ol" else "- "
                    list_items.append(f"{prefix}{li_text}")
            if list_items:
                blocks.append("\n".join(list_items))

        elif tag_name == "p":
            # Avoid duplicate if paragraph is already inside table/details/list
            if elem.parent and elem.parent.name in ("table", "details", "li", "td", "th", "dd", "dt"):
                continue
            p_text = elem.get_text(" ", strip=True)
            if p_text:
                blocks.append(p_text)

    # Append JSON-LD structured data if any
    if json_ld_sections:
        blocks.extend(json_ld_sections)

    content = "\n\n".join(b for b in blocks if b)
    if not content:
        content = clean_text(main.get_text(" "))

    return title, clean_text(content)


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
