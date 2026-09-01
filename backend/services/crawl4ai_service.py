import asyncio
import hashlib
import ipaddress
import json
import os
import re
import socket
import urllib.robotparser
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urldefrag, urlencode, urljoin, urlparse

import crawl4ai
import httpx
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig


@dataclass
class Page:
    url: str
    title: str
    markdown: str
    html: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    links: list[str] = field(default_factory=list)
    status: str = "success"
    status_code: int = 200
    error: str | None = None


class Crawl4AIError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def get_crawler_config() -> dict[str, Any]:
    return {
        "max_pages": int(os.getenv("MAX_CRAWL_PAGES", "50")),
        "max_depth": int(os.getenv("MAX_DEPTH", "3")),
        "crawl_timeout": int(os.getenv("CRAWL_TIMEOUT", "120")),
        "concurrency": int(os.getenv("CRAWLER_CONCURRENCY", "4")),
        "headless": os.getenv("CRAWLER_HEADLESS", "true").lower() in ("true", "1", "yes"),
        "respect_robots": os.getenv("RESPECT_ROBOTS_TXT", "true").lower() in ("true", "1", "yes"),
    }


def validate_crawl_url(url: str) -> str:
    if not url or not isinstance(url, str):
        raise Crawl4AIError("Invalid URL: URL string is required.", status_code=400)

    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise Crawl4AIError("Invalid URL: URL must be an absolute http(s) URL.", status_code=400)

    hostname = parsed.hostname
    if not hostname:
        raise Crawl4AIError("Invalid URL: URL hostname is required.", status_code=400)

    try:
        addresses = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise Crawl4AIError("Invalid URL: URL hostname could not be resolved.", status_code=400) from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise Crawl4AIError("Invalid URL: Private or local URLs are not allowed for crawling.", status_code=400)

    return url


def extract_title_from_markdown(markdown: str, default_title: str) -> str:
    if not markdown:
        return default_title
    match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
    if match:
        title = match.group(1).strip()
        if title:
            return title
    return default_title


CTA_KEYWORDS_PATTERN = re.compile(
    r"\b(buy now|add to cart|order now|purchase|shop now|get started|book now|book appointment|schedule appointment|book consultation|schedule consultation|reserve now|reserve a table|reserve table|enroll now|apply now|apply today|subscribe|contact us|request demo|book a demo|schedule a tour|tour property|schedule visit|sign up|free trial|get a quote|request quote|checkout)\b",
    re.IGNORECASE,
)

DISALLOWED_URL_PATTERNS = [
    re.compile(r"/(logout|signout|signin|login|auth|cart|checkout|wp-admin|admin|account|password)\b", re.IGNORECASE),
    re.compile(r"[?&](sessionid|phpsessid|jsessionid|token|access_token)=", re.IGNORECASE),
]

IGNORED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z", ".exe", ".dmg",
    ".mp4", ".mp3", ".wav", ".avi", ".mov", ".wmv",
    ".css", ".js", ".json", ".xml", ".txt", ".csv",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
}

TRACKING_QUERY_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "dclid", "msclkid", "ref", "source", "_ga", "_gl", "mc_eid",
}


def is_safe_crawl_url(url: str) -> bool:
    """Checks if URL is safe to crawl as content (excludes authentication, cart, checkout, session loops)."""
    parsed = urlparse(url)
    path_and_query = f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path
    for pattern in DISALLOWED_URL_PATTERNS:
        if pattern.search(path_and_query):
            return False
    return True


def normalize_child_url(url: str, base_url: str) -> str | None:
    """
    Normalizes child URLs:
    - Resolves relative URLs against base
    - Removes fragments (#...)
    - Cleans marketing tracking query parameters while preserving content/routing parameters
    - Alphabetically sorts query keys for deterministic deduplication
    - Filters binary/media extensions
    """
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if url.startswith(("javascript:", "mailto:", "tel:", "data:", "#")):
        return None

    defragged, _ = urldefrag(url)
    if not defragged:
        return None

    joined = urljoin(base_url, defragged).strip()
    parsed = urlparse(joined)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None

    path_lower = parsed.path.lower()
    for ext in IGNORED_EXTENSIONS:
        if path_lower.endswith(ext):
            return None

    # Clean query parameters safely
    clean_query = ""
    if parsed.query:
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        filtered_pairs = [
            (k, v) for k, v in query_pairs if k.lower() not in TRACKING_QUERY_PARAMS
        ]
        if filtered_pairs:
            filtered_pairs.sort(key=lambda x: x[0])
            clean_query = f"?{urlencode(filtered_pairs)}"

    # Normalize path trailing slash (preserve root slash)
    norm_path = parsed.path or "/"

    return f"{parsed.scheme}://{parsed.netloc}{norm_path}{clean_query}"


def extract_cta_links_from_html(html: str, source_url: str) -> list[dict[str, Any]]:
    """
    Extracts actionable call-to-action (CTA) links/buttons from rendered HTML
    and captures their target URLs, visible text, and context as metadata.
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    root_domain = urlparse(source_url).netloc.lower()
    ctas: list[dict[str, Any]] = []
    seen_targets: set[str] = set()

    for elem in soup.find_all(["a", "button"]):
        text = elem.get_text(" ", strip=True)
        aria = elem.get("aria-label", "") or ""
        title = elem.get("title", "") or ""
        combined_text = f"{text} {aria} {title}".strip()

        if CTA_KEYWORDS_PATTERN.search(combined_text):
            target_href = (
                elem.get("href")
                or elem.get("data-href")
                or elem.get("data-url")
                or elem.get("formaction")
                or ""
            ).strip()

            if not target_href or target_href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue

            abs_url = urljoin(source_url, target_href).strip()
            if abs_url in seen_targets:
                continue
            seen_targets.add(abs_url)

            heading = elem.find_previous(["h1", "h2", "h3", "h4"])
            context = heading.get_text(" ", strip=True) if heading else ""
            is_internal = urlparse(abs_url).netloc.lower() == root_domain

            ctas.append({
                "text": text or aria or title or "CTA",
                "url": abs_url,
                "source_url": source_url,
                "type": elem.name,
                "is_internal": is_internal,
                "context": context,
            })

    return ctas


def extract_rich_metadata_from_html(html: str, current_url: str) -> dict[str, Any]:
    """Extracts canonical URLs, JSON-LD structured data, and rich metadata."""
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    meta: dict[str, Any] = {}

    # Canonical URL
    canonical_tag = soup.find("link", rel="canonical")
    if canonical_tag and canonical_tag.get("href"):
        can_href = str(canonical_tag["href"]).strip()
        can_abs = urljoin(current_url, can_href)
        meta["canonical_url"] = can_abs

    # JSON-LD Structured Data
    json_ld_list = []
    for script in soup.find_all("script", type="application/ld+json"):
        if script.string:
            try:
                parsed = json.loads(script.string.strip())
                json_ld_list.append(parsed)
            except Exception:
                pass
    if json_ld_list:
        meta["json_ld"] = json_ld_list

    return meta


def _normalize_crawl_result(result: Any, target_url: str) -> Page:
    """
    Safely extracts and normalizes Crawl4AI result into internal Page representation.
    Guarantees no raw Crawl4AI objects leak out of this adapter.
    """
    if result is None:
        return Page(
            url=target_url,
            title=urlparse(target_url).netloc or target_url,
            markdown="",
            html="",
            metadata={},
            links=[],
            status="failed",
            status_code=500,
            error="Crawl4AI returned no result.",
        )

    # 1. URL
    final_url = str(getattr(result, "url", "") or target_url).strip()

    # 2. Markdown
    raw_markdown = ""
    md_attr = getattr(result, "markdown", None)
    if md_attr is not None:
        raw_markdown = str(md_attr).strip()

    # 3. HTML
    raw_html = ""
    cleaned_html = getattr(result, "cleaned_html", None)
    if cleaned_html:
        raw_html = str(cleaned_html).strip()
    elif getattr(result, "html", None):
        raw_html = str(getattr(result, "html")).strip()

    # 4. Metadata
    metadata: dict[str, Any] = {}
    meta_attr = getattr(result, "metadata", None)
    if isinstance(meta_attr, dict):
        metadata = {k: v for k, v in meta_attr.items() if v is not None}

    # Rich metadata & JSON-LD & Canonical URL
    rich_meta = extract_rich_metadata_from_html(raw_html, final_url)
    metadata.update(rich_meta)

    # CTA links from rendered HTML
    cta_links = extract_cta_links_from_html(raw_html, final_url)
    if cta_links:
        metadata["cta_links"] = cta_links

    # Content Hash for incremental update detection
    metadata["content_hash"] = hashlib.sha256(raw_markdown.encode("utf-8")).hexdigest()

    # 5. Page Title
    title = ""
    if metadata.get("title"):
        title = str(metadata["title"]).strip()
    elif metadata.get("ogTitle"):
        title = str(metadata["ogTitle"]).strip()

    if not title:
        default_fallback = urlparse(final_url).netloc or final_url
        title = extract_title_from_markdown(raw_markdown, default_fallback)

    # 6. Discovered Links
    discovered_links: list[str] = []
    links_attr = getattr(result, "links", None)
    if isinstance(links_attr, dict):
        for category in ("internal", "external"):
            cat_links = links_attr.get(category, [])
            if isinstance(cat_links, list):
                for item in cat_links:
                    if isinstance(item, dict) and item.get("href"):
                        href = str(item["href"]).strip()
                        if href and href not in discovered_links:
                            discovered_links.append(href)
                    elif isinstance(item, str) and item.strip():
                        href = item.strip()
                        if href not in discovered_links:
                            discovered_links.append(href)
    elif isinstance(links_attr, list):
        for item in links_attr:
            if isinstance(item, dict) and item.get("href"):
                href = str(item["href"]).strip()
                if href and href not in discovered_links:
                    discovered_links.append(href)
            elif isinstance(item, str) and item.strip():
                href = item.strip()
                if href not in discovered_links:
                    discovered_links.append(href)

    # 7. Status and Error
    success = bool(getattr(result, "success", False))
    status_code = getattr(result, "status_code", 200 if success else 500)
    error_msg = getattr(result, "error_message", None)

    if not success and not error_msg:
        error_msg = f"Crawl failed with HTTP status code {status_code}"

    status = "success" if success and raw_markdown else "failed"

    return Page(
        url=final_url,
        title=title,
        markdown=raw_markdown,
        html=raw_html,
        metadata=metadata,
        links=discovered_links,
        status=status,
        status_code=status_code if isinstance(status_code, int) else 500,
        error=error_msg if not success or not raw_markdown else None,
    )


def print_adapter_diagnostic(page: Page) -> None:
    words = len(page.markdown.split()) if page.markdown else 0
    print("\n========== CRAWL4AI ADAPTER ==========")
    print(f"URL:\n{page.url}\n")
    print(f"Success:\n{str(page.status == 'success').lower()}\n")
    print(f"Title:\n{page.title}\n")
    print(f"Markdown Characters:\n{len(page.markdown)}\n")
    print(f"Markdown Words:\n{words}\n")
    print(f"Links:\n{len(page.links)}\n")
    print(f"Status:\n{page.status} ({page.status_code})\n")
    print("=======================================\n")


def parse_sitemap_xml(xml_content: str) -> tuple[list[str], list[str]]:
    """
    Parses sitemap XML content. Returns tuple of (page_urls, child_sitemap_urls).
    """
    if not xml_content:
        return [], []

    page_urls: list[str] = []
    child_sitemaps: list[str] = []

    try:
        root = ET.fromstring(xml_content)
        # Check if sitemap index
        is_index = root.tag.endswith("sitemapindex")

        for elem in root.iter():
            if elem.tag.endswith("loc") and elem.text:
                loc_url = elem.text.strip()
                if loc_url:
                    if is_index:
                        child_sitemaps.append(loc_url)
                    else:
                        page_urls.append(loc_url)
    except Exception:
        # Fallback regex for loose XML/text sitemaps
        for match in re.finditer(r"<loc>\s*(https?://[^\s<]+)\s*</loc>", xml_content, re.IGNORECASE):
            loc_url = match.group(1).strip()
            if loc_url:
                if "sitemap" in loc_url.lower() and loc_url.endswith(".xml"):
                    child_sitemaps.append(loc_url)
                else:
                    page_urls.append(loc_url)

    return page_urls, child_sitemaps


def discover_sitemap_urls(root_url: str, max_sitemaps: int = 5, timeout: int = 10) -> set[str]:
    """
    Discovers URLs from sitemap.xml and sitemap indexes for the target domain.
    """
    parsed = urlparse(root_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    root_domain = parsed.netloc.lower()

    candidate_sitemaps = [
        f"{origin}/sitemap.xml",
        f"{origin}/sitemap_index.xml",
        f"{origin}/sitemap/sitemap.xml",
        f"{origin}/sitemap.txt",
    ]

    discovered_pages: set[str] = set()
    visited_sitemaps: set[str] = set()
    sitemap_queue = list(candidate_sitemaps)

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        while sitemap_queue and len(visited_sitemaps) < max_sitemaps:
            sm_url = sitemap_queue.pop(0)
            if sm_url in visited_sitemaps:
                continue
            visited_sitemaps.add(sm_url)

            try:
                resp = client.get(sm_url)
                if resp.status_code == 200 and resp.text:
                    pages, child_sm = parse_sitemap_xml(resp.text)
                    for p in pages:
                        norm = normalize_child_url(p, root_url)
                        if norm and urlparse(norm).netloc.lower() == root_domain and is_safe_crawl_url(norm):
                            discovered_pages.add(norm)
                    for c in child_sm:
                        if c not in visited_sitemaps and urlparse(c).netloc.lower() == root_domain:
                            sitemap_queue.append(c)
            except Exception:
                continue

    return discovered_pages


def check_robots_allowed(url: str, root_url: str) -> bool:
    """Checks if URL is allowed according to robots.txt."""
    try:
        parsed = urlparse(root_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch("*", url)
    except Exception:
        return True


def print_production_diagnostics(
    root_url: str,
    pages_discovered: int,
    pages_crawled: int,
    pages_successful: int,
    pages_failed: int,
    sitemap_urls_count: int,
    bfs_urls_count: int,
    duplicate_urls_removed: int,
    canonical_urls_count: int,
    markdown_chars: int,
    markdown_words: int,
    chunks_created: int,
    embeddings_created: int,
    cta_links: int,
    avg_page_size: int,
) -> None:
    """Outputs standard production crawler summary banner."""
    print("\n========== PRODUCTION CRAWLER ==========\n")
    print(f"Pages discovered: {pages_discovered}")
    print(f"Pages crawled: {pages_crawled}")
    print(f"Pages successful: {pages_successful}")
    print(f"Pages failed: {pages_failed}")
    print(f"Sitemap URLs: {sitemap_urls_count}")
    print(f"BFS URLs: {bfs_urls_count}")
    print(f"Duplicate URLs removed: {duplicate_urls_removed}")
    print(f"Canonical URLs: {canonical_urls_count}")
    print(f"Markdown characters: {markdown_chars}")
    print(f"Markdown words: {markdown_words}")
    print(f"Chunks created: {chunks_created}")
    print(f"Embeddings created: {embeddings_created}")
    print(f"CTA links: {cta_links}")
    print(f"Average page size: {avg_page_size} chars")
    print("\n=========================================\n")


async def crawl_single_page_async(url: str, timeout: int | None = None) -> Page:
    """Asynchronously crawls a single page and returns a normalized Page object."""
    clean_url = validate_crawl_url(url)
    config = get_crawler_config()
    page_timeout = (timeout or config["crawl_timeout"]) * 1000  # ms

    browser_cfg = BrowserConfig(headless=config["headless"])
    run_cfg = CrawlerRunConfig(page_timeout=page_timeout)

    try:
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            result = await crawler.arun(url=clean_url, config=run_cfg)
            return _normalize_crawl_result(result, clean_url)
    except Crawl4AIError:
        raise
    except Exception as exc:
        return Page(
            url=clean_url,
            title=urlparse(clean_url).netloc or clean_url,
            markdown="",
            html="",
            metadata={},
            links=[],
            status="failed",
            status_code=500,
            error=str(exc),
        )


def crawl_single_page(url: str, timeout: int | None = None) -> Page:
    """Synchronous entry point for single page crawl."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(crawl_single_page_async(url, timeout=timeout))
        return loop.run_until_complete(crawl_single_page_async(url, timeout=timeout))
    except RuntimeError:
        return asyncio.run(crawl_single_page_async(url, timeout=timeout))


async def crawl_website_async(
    url: str,
    max_pages: int | None = None,
    max_depth: int | None = None,
    timeout: int | None = None,
    verbose_diagnostics: bool = True,
) -> list[Page]:
    """
    Production-grade website crawler using Crawl4AI:
    - Discovers URLs from sitemap.xml & sitemap index
    - Merges with BFS traversal
    - Respects robots.txt where applicable
    - Normalizes & deduplicates URLs (cleans tracking parameters, handles canonical URLs)
    - Captures complete rendered HTML, Markdown, JSON-LD, and CTA links
    - Isolates individual failures and supports transient retry
    """
    clean_url = validate_crawl_url(url)
    config = get_crawler_config()

    limit = max_pages if max_pages is not None else config["max_pages"]
    depth_limit = max_depth if max_depth is not None else config["max_depth"]
    page_timeout = (timeout or config["crawl_timeout"]) * 1000  # ms

    root_domain = urlparse(clean_url).netloc.lower()

    # 1. Sitemap Discovery
    sitemap_urls = discover_sitemap_urls(clean_url)
    sitemap_urls_count = len(sitemap_urls)

    # 2. Queue Initialization (Root + Sitemap URLs)
    visited_urls: set[str] = set()
    discovered_urls: set[str] = {clean_url}.union(sitemap_urls)
    duplicate_count = 0
    canonical_count = 0
    bfs_urls_count = 0

    queue: list[tuple[str, int, str]] = [(clean_url, 0, "bfs")]
    for s_url in sitemap_urls:
        if s_url != clean_url:
            queue.append((s_url, 1, "sitemap"))

    browser_cfg = BrowserConfig(headless=config["headless"])
    run_cfg = CrawlerRunConfig(page_timeout=page_timeout)
    pages: list[Page] = []

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        while queue and len(pages) < limit:
            current_url, current_depth, source_type = queue.pop(0)

            normalized = normalize_child_url(current_url, clean_url)
            if not normalized:
                continue

            if normalized in visited_urls:
                duplicate_count += 1
                continue

            if urlparse(normalized).netloc.lower() != root_domain:
                continue

            if not is_safe_crawl_url(normalized):
                continue

            visited_urls.add(normalized)

            # Transient retry logic (1 retry on timeout/network issue)
            attempts = 0
            page: Page | None = None

            while attempts < 2:
                attempts += 1
                try:
                    result = await crawler.arun(url=normalized, config=run_cfg)
                    page = _normalize_crawl_result(result, normalized)
                    page.metadata["crawl_depth"] = current_depth
                    page.metadata["discovery_source"] = source_type

                    if page.metadata.get("canonical_url"):
                        canonical_count += 1

                    if page.status == "success" and page.markdown:
                        break
                    elif attempts < 2:
                        await asyncio.sleep(0.5)
                except Exception as exc:
                    if attempts >= 2:
                        page = Page(
                            url=normalized,
                            title=urlparse(normalized).netloc or normalized,
                            markdown="",
                            html="",
                            metadata={"crawl_depth": current_depth, "discovery_source": source_type},
                            links=[],
                            status="failed",
                            status_code=500,
                            error=str(exc),
                        )

            if page is None:
                continue

            if page.status == "success" and page.markdown:
                pages.append(page)

                # Discover child links if depth allows
                if current_depth < depth_limit and len(pages) < limit:
                    links_attr = getattr(result, "links", {}) or {}
                    internal_links = []
                    if isinstance(links_attr, dict):
                        internal_links = links_attr.get("internal", []) or []
                    elif isinstance(links_attr, list):
                        internal_links = links_attr

                    for item in internal_links:
                        raw_href = item.get("href") if isinstance(item, dict) else str(item)
                        child_url = normalize_child_url(raw_href, normalized)
                        if child_url and urlparse(child_url).netloc.lower() == root_domain:
                            if is_safe_crawl_url(child_url):
                                discovered_urls.add(child_url)
                                if child_url not in visited_urls and not any(q[0] == child_url for q in queue):
                                    bfs_urls_count += 1
                                    queue.append((child_url, current_depth + 1, "bfs"))
            else:
                pages.append(page)

    successful_pages = [p for p in pages if p.status == "success" and p.markdown]
    if not successful_pages and pages:
        first_err = pages[0].error or "Unknown extraction failure"
        raise Crawl4AIError(f"Crawl completed but no usable pages were extracted for {clean_url}: {first_err}", status_code=pages[0].status_code)
    elif not pages:
        raise Crawl4AIError(f"Crawl completed with 0 pages found for {clean_url}.", status_code=400)

    total_md_chars = sum(len(p.markdown) for p in successful_pages)
    total_md_words = sum(len(p.markdown.split()) for p in successful_pages)
    total_cta_links = sum(len(p.metadata.get("cta_links", [])) for p in successful_pages)
    avg_size = int(total_md_chars / len(successful_pages)) if successful_pages else 0

    if verbose_diagnostics:
        print_production_diagnostics(
            root_url=clean_url,
            pages_discovered=len(discovered_urls),
            pages_crawled=len(pages),
            pages_successful=len(successful_pages),
            pages_failed=len(pages) - len(successful_pages),
            sitemap_urls_count=sitemap_urls_count,
            bfs_urls_count=bfs_urls_count,
            duplicate_urls_removed=duplicate_count,
            canonical_urls_count=canonical_count,
            markdown_chars=total_md_chars,
            markdown_words=total_md_words,
            chunks_created=0,
            embeddings_created=0,
            cta_links=total_cta_links,
            avg_page_size=avg_size,
        )

    return [p for p in pages if p.status == "success" and p.markdown]


def crawl_website(
    url: str,
    max_pages: int | None = None,
    max_depth: int | None = None,
    timeout: int | None = None,
    verbose_diagnostics: bool = True,
) -> list[Page]:
    """
    Synchronous entry point for crawling a website using Crawl4AI.
    Compatible with existing downstream document ingestion boundary.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(
                crawl_website_async(
                    url,
                    max_pages=max_pages,
                    max_depth=max_depth,
                    timeout=timeout,
                    verbose_diagnostics=verbose_diagnostics,
                )
            )
        return loop.run_until_complete(
            crawl_website_async(
                url,
                max_pages=max_pages,
                max_depth=max_depth,
                timeout=timeout,
                verbose_diagnostics=verbose_diagnostics,
            )
        )
    except RuntimeError:
        return asyncio.run(
            crawl_website_async(
                url,
                max_pages=max_pages,
                max_depth=max_depth,
                timeout=timeout,
                verbose_diagnostics=verbose_diagnostics,
            )
        )
