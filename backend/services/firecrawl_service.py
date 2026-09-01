import ipaddress
import os
import re
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

import httpx


@dataclass
class Page:
    url: str
    title: str
    markdown: str
    metadata: dict[str, Any] = field(default_factory=dict)
    links: list[str] = field(default_factory=list)


@dataclass
class CrawlAuditReport:
    seed_url: str
    discovered_urls: int = 0
    eligible_urls: int = 0
    crawled_urls: int = 0
    stored_documents: int = 0
    chunked_documents: int = 0
    total_chunks: int = 0
    embedded_chunks: int = 0
    duplicate_urls_removed: int = 0
    canonical_urls: int = 0
    max_depth_reached: int = 0
    crawl_duration_seconds: float = 0.0
    skipped_urls: dict[str, str] = field(default_factory=dict)
    failed_urls: dict[str, str] = field(default_factory=dict)
    discovered_list: list[str] = field(default_factory=list)
    eligible_list: list[str] = field(default_factory=list)
    crawled_list: list[str] = field(default_factory=list)


class FirecrawlError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def get_firecrawl_config() -> dict[str, Any]:
    return {
        "api_key": os.getenv("FIRECRAWL_API_KEY", "").strip(),
        "api_base": os.getenv("FIRECRAWL_API_BASE", "https://api.firecrawl.dev").rstrip("/"),
        "max_pages": int(os.getenv("MAX_CRAWL_PAGES", "20")),
        "max_depth": int(os.getenv("MAX_DEPTH", "2")),
        "crawl_timeout": int(os.getenv("CRAWL_TIMEOUT", "120")),
    }


TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "source", "_ga", "mc_cid", "mc_eid",
}

DISALLOWED_PATH_PATTERNS = [
    (re.compile(r"/(login|signup|signin|logout|auth|admin|wp-admin|password)\b", re.IGNORECASE), "disallowed_path_auth"),
    (re.compile(r"/(cart|checkout|basket|bag|order-received)\b", re.IGNORECASE), "disallowed_path_cart"),
    (re.compile(r"[?&](sessionid|phpsessid|jsessionid|token|access_token)=", re.IGNORECASE), "disallowed_path_session"),
]

IGNORED_FILE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp",
    ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z", ".exe", ".dmg", ".pkg",
    ".mp3", ".mp4", ".mov", ".avi", ".wav", ".woff", ".woff2", ".ttf", ".eot",
    ".css", ".js", ".map",
}


def normalize_crawl_url(url: str, base_url: str = "") -> str:
    """Normalizes URL by resolving relative links, stripping fragments and tracking query params."""
    if not url:
        return ""
    if base_url:
        url = urljoin(base_url, url)
    url = url.strip()
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""

    # Filter out tracking query params
    clean_params = []
    if parsed.query:
        for k, v in parse_qsl(parsed.query, keep_blank_values=True):
            if k.lower() not in TRACKING_PARAMS:
                clean_params.append((k, v))
    clean_query = urlencode(clean_params)

    path = parsed.path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    clean = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        path=path,
        query=clean_query,
        fragment="",
    )
    return clean.geturl()


def is_url_eligible_for_crawl(
    url: str,
    seed_domain: str,
    max_depth: int = 3,
    current_depth: int = 0,
) -> tuple[bool, str]:
    """
    Evaluates whether a discovered internal link is eligible for crawling.
    Returns (is_eligible, reason_if_ineligible).
    """
    if not url:
        return False, "empty_url"

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False, "invalid_scheme"

    host = (parsed.hostname or "").lower()
    seed_host = seed_domain.lower()
    if host != seed_host and not host.endswith("." + seed_host) and not seed_host.endswith("." + host):
        return False, "external_domain"

    # Check depth
    if current_depth > max_depth:
        return False, f"exceeded_max_depth_{max_depth}"

    # Check file extension
    path_lower = parsed.path.lower()
    for ext in IGNORED_FILE_EXTENSIONS:
        if path_lower.endswith(ext):
            return False, f"ignored_extension_{ext}"

    # Check disallowed path patterns
    for pattern, reason in DISALLOWED_PATH_PATTERNS:
        if pattern.search(url):
            return False, reason

    return True, "eligible"


def extract_discovered_links_from_markdown(markdown: str, page_url: str) -> list[str]:
    """Discovers internal and external links from markdown [text](url) syntax."""
    if not markdown:
        return []
    links = []
    seen = set()
    for match in re.finditer(r"\[([^\]]*)\]\((https?://[^\)\s]+|/[^\)\s]+)\)", markdown):
        raw_url = match.group(2).strip()
        norm = normalize_crawl_url(raw_url, base_url=page_url)
        if norm and norm not in seen:
            seen.add(norm)
            links.append(norm)
    return links


def validate_crawl_url(url: str) -> str:
    if not url or not isinstance(url, str):
        raise FirecrawlError("Invalid URL: URL string is required.", status_code=400)

    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise FirecrawlError("Invalid URL: URL must be an absolute http(s) URL.", status_code=400)

    hostname = parsed.hostname
    if not hostname:
        raise FirecrawlError("Invalid URL: URL hostname is required.", status_code=400)

    try:
        addresses = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise FirecrawlError("Invalid URL: URL hostname could not be resolved.", status_code=400) from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise FirecrawlError("Invalid URL: Private or local URLs are not allowed for crawling.", status_code=400)

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


def extract_cta_links_from_markdown(markdown: str, page_url: str) -> list[dict[str, Any]]:
    """Extracts actionable CTA links from markdown links matching conversion intents."""
    cta_links = []
    if not markdown:
        return cta_links

    for match in re.finditer(r"\[([^\]]+)\]\((https?://[^\)\s]+)\)", markdown):
        text, url = match.group(1).strip(), match.group(2).strip()
        if CTA_KEYWORDS_PATTERN.search(text):
            cta_links.append({
                "text": text,
                "url": url,
                "source_url": page_url,
                "type": "markdown_link",
            })
    return cta_links


def scrape_single_page_with_audit(
    url: str,
    timeout: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[list[Page], CrawlAuditReport]:
    """Scrape exactly the submitted URL without scheduling link discovery."""
    config = get_firecrawl_config()
    api_key = config["api_key"]
    if not api_key:
        raise FirecrawlError(
            "Authentication failed: FIRECRAWL_API_KEY environment variable is missing or empty.",
            status_code=401,
        )

    clean_url = normalize_crawl_url(validate_crawl_url(url))
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "url": clean_url,
        "formats": ["markdown"],
        "onlyMainContent": True,
        "waitFor": 2000,
    }
    started_at = time.time()

    if cancel_check and cancel_check():
        raise FirecrawlError("Scrape cancelled before completion.", status_code=409)

    try:
        request_timeout = timeout or config["crawl_timeout"]
        with httpx.Client(timeout=httpx.Timeout(request_timeout, connect=10.0)) as client:
            response = client.post(f"{config['api_base']}/v1/scrape", json=payload, headers=headers)
        if response.status_code in {401, 403}:
            raise FirecrawlError("Authentication failed: Invalid or unauthorized Firecrawl API key.", status_code=401)
        if response.status_code in {402, 429}:
            raise FirecrawlError("API quota exceeded: Firecrawl usage limit reached or payment required.", status_code=429)
        if response.status_code == 400:
            raise FirecrawlError(f"Invalid URL or bad request to Firecrawl: {response.text}", status_code=400)
        if response.status_code >= 500:
            raise FirecrawlError(f"Firecrawl service unavailable (HTTP {response.status_code}).", status_code=502)
        response.raise_for_status()
        response_data = response.json()
    except httpx.TimeoutException as exc:
        raise FirecrawlError("Firecrawl request timed out during page scrape.", status_code=504) from exc
    except httpx.TransportError as exc:
        raise FirecrawlError(f"Firecrawl network/connection error: {exc}", status_code=502) from exc
    except FirecrawlError:
        raise
    except Exception as exc:
        raise FirecrawlError(f"Failed to scrape page with Firecrawl: {exc}", status_code=500) from exc

    if cancel_check and cancel_check():
        raise FirecrawlError("Scrape cancelled before completion.", status_code=409)
    if not response_data.get("success", True):
        error_msg = response_data.get("error") or "Unknown Firecrawl error"
        raise FirecrawlError(f"Firecrawl API error: {error_msg}", status_code=400)

    item = response_data.get("data") or {}
    markdown = str(item.get("markdown") or "").strip()
    metadata = dict(item.get("metadata") or {})
    status_code = metadata.get("statusCode")
    if not markdown or (status_code and int(status_code) >= 400):
        raise FirecrawlError("Firecrawl completed but no usable text/markdown page was extracted.", status_code=400)

    discovered = extract_discovered_links_from_markdown(markdown, clean_url)
    raw_title = metadata.get("title") or metadata.get("ogTitle") or ""
    title = extract_title_from_markdown(markdown, str(raw_title) or urlparse(clean_url).netloc or clean_url)
    if "cta_links" not in metadata or not metadata["cta_links"]:
        extracted_ctas = extract_cta_links_from_markdown(markdown, clean_url)
        if extracted_ctas:
            metadata["cta_links"] = extracted_ctas

    page = Page(url=clean_url, title=title, markdown=markdown, metadata=metadata, links=discovered)
    audit_report = CrawlAuditReport(
        seed_url=clean_url,
        discovered_urls=1 + len(discovered),
        eligible_urls=1,
        crawled_urls=1,
        stored_documents=1,
        canonical_urls=1 if metadata.get("canonicalURL") or metadata.get("canonical_url") else 0,
        max_depth_reached=0,
        crawl_duration_seconds=time.time() - started_at,
        skipped_urls={link: "single_page_mode" for link in discovered},
        discovered_list=sorted(discovered),
        eligible_list=[clean_url],
        crawled_list=[clean_url],
    )
    return [page], audit_report


def crawl_website_with_audit(
    url: str,
    max_pages: int | None = None,
    max_depth: int | None = None,
    timeout: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[list[Page], CrawlAuditReport]:
    """
    Crawls a website using Firecrawl API and returns (pages, CrawlAuditReport).
    Each Page contains url, title, markdown, metadata, and discovered links.
    """
    config = get_firecrawl_config()
    api_key = config["api_key"]

    if not api_key:
        raise FirecrawlError(
            "Authentication failed: FIRECRAWL_API_KEY environment variable is missing or empty.",
            status_code=401,
        )

    clean_url = validate_crawl_url(url)
    limit = max_pages or config["max_pages"]
    depth = max_depth or config["max_depth"]
    crawl_timeout = timeout or config["crawl_timeout"]
    api_base = config["api_base"]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "url": clean_url,
        "limit": limit,
        # Firecrawl maxDepth is absolute URL-path depth. The product setting is
        # discovery depth from the submitted seed, so use the matching API
        # field or nested seed URLs would incorrectly crawl only one page.
        "maxDiscoveryDepth": depth,
        "scrapeOptions": {
            "formats": ["markdown"],
            "onlyMainContent": True,
            "waitFor": 2000,
        },
    }

    crawl_endpoint = f"{api_base}/v1/crawl"

    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            response = client.post(crawl_endpoint, json=payload, headers=headers)

            if response.status_code in {401, 403}:
                raise FirecrawlError("Authentication failed: Invalid or unauthorized Firecrawl API key.", status_code=401)
            elif response.status_code in {402, 429}:
                raise FirecrawlError("API quota exceeded: Firecrawl usage limit reached or payment required.", status_code=429)
            elif response.status_code == 400:
                raise FirecrawlError(f"Invalid URL or bad request to Firecrawl: {response.text}", status_code=400)
            elif response.status_code >= 500:
                raise FirecrawlError(f"Firecrawl service unavailable (HTTP {response.status_code}).", status_code=502)

            response.raise_for_status()
            res_data = response.json()

    except httpx.TimeoutException as exc:
        raise FirecrawlError("Firecrawl request timed out during crawl initiation.", status_code=504) from exc
    except httpx.TransportError as exc:
        raise FirecrawlError(f"Firecrawl network/connection error: {exc}", status_code=502) from exc
    except FirecrawlError:
        raise
    except Exception as exc:
        raise FirecrawlError(f"Failed to initiate Firecrawl crawl: {exc}", status_code=500) from exc

    if not res_data.get("success", True) and not res_data.get("id"):
        error_msg = res_data.get("error") or "Unknown Firecrawl error"
        raise FirecrawlError(f"Firecrawl API error: {error_msg}", status_code=400)

    job_id = res_data.get("id")
    if not job_id:
        raise FirecrawlError("Firecrawl API response did not contain a valid job ID.", status_code=500)

    # Poll status endpoint until completed or timeout
    status_url = f"{api_base}/v1/crawl/{job_id}"
    start_time = time.time()
    poll_interval = 2.0
    pages_data: list[dict[str, Any]] = []

    with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        while True:
            if cancel_check and cancel_check():
                raise FirecrawlError("Crawl cancelled before completion.", status_code=409)
            elapsed = time.time() - start_time
            if elapsed > crawl_timeout:
                raise FirecrawlError(
                    f"Timeout: Firecrawl crawl exceeded maximum allowed duration of {crawl_timeout} seconds.",
                    status_code=504,
                )

            try:
                poll_res = client.get(status_url, headers=headers)
                if poll_res.status_code in {401, 403}:
                    raise FirecrawlError("Authentication failed during status polling.", status_code=401)
                elif poll_res.status_code in {402, 429}:
                    raise FirecrawlError("API quota exceeded during status polling.", status_code=429)

                poll_res.raise_for_status()
                poll_json = poll_res.json()
            except FirecrawlError:
                raise
            except Exception as exc:
                if elapsed + poll_interval >= crawl_timeout:
                    raise FirecrawlError(f"Firecrawl polling error: {exc}", status_code=502) from exc
                time.sleep(poll_interval)
                continue

            status = str(poll_json.get("status", "")).lower()
            if status == "completed":
                pages_data = poll_json.get("data", [])

                next_url = poll_json.get("next")
                while next_url:
                    if cancel_check and cancel_check():
                        raise FirecrawlError("Crawl cancelled before pagination completed.", status_code=409)
                    try:
                        next_res = client.get(next_url, headers=headers)
                        next_res.raise_for_status()
                        next_json = next_res.json()
                        pages_data.extend(next_json.get("data", []))
                        next_url = next_json.get("next")
                    except Exception:
                        break
                break

            elif status in {"failed", "cancelled", "error"}:
                err_detail = poll_json.get("error") or "Crawl process failed on Firecrawl."
                raise FirecrawlError(f"Firecrawl job failed: {err_detail}", status_code=500)

            time.sleep(poll_interval)

    pages: list[Page] = []
    seen_urls: set[str] = set()
    seed_domain = urlparse(clean_url).netloc
    all_discovered_links: set[str] = set()
    skipped_urls: dict[str, str] = {}
    duplicate_count = 0
    canonical_count = 0
    max_depth_seen = 0

    for item in pages_data:
        markdown = (item.get("markdown") or "").strip()
        metadata = item.get("metadata") or {}

        status_code = metadata.get("statusCode")
        if status_code and status_code >= 400:
            continue

        raw_page_url = metadata.get("sourceURL") or metadata.get("url") or item.get("url") or clean_url
        page_url = normalize_crawl_url(str(raw_page_url).strip())
        if not page_url:
            continue

        # Extract all links on this page
        discovered = extract_discovered_links_from_markdown(markdown, page_url)
        all_discovered_links.update(discovered)

        if page_url in seen_urls:
            duplicate_count += 1
            continue

        if metadata.get("canonicalURL") or metadata.get("canonical_url"):
            canonical_count += 1

        depth = int(metadata.get("depth", 0))
        if depth > max_depth_seen:
            max_depth_seen = depth

        seen_urls.add(page_url)
        raw_title = metadata.get("title") or metadata.get("ogTitle") or ""
        title = extract_title_from_markdown(markdown, str(raw_title) or urlparse(page_url).netloc or page_url)

        if "cta_links" not in metadata or not metadata["cta_links"]:
            extracted_ctas = extract_cta_links_from_markdown(markdown, page_url)
            if extracted_ctas:
                metadata["cta_links"] = extracted_ctas

        pages.append(
            Page(
                url=page_url,
                title=title,
                markdown=markdown,
                metadata=metadata,
                links=discovered,
            )
        )

    if not pages:
        raise FirecrawlError("Firecrawl completed but no usable text/markdown pages were extracted.", status_code=400)

    # Classify all discovered links for audit report
    eligible_links: set[str] = set()
    for link in all_discovered_links:
        eligible, reason = is_url_eligible_for_crawl(link, seed_domain, max_depth=depth)
        if eligible:
            eligible_links.add(link)
        else:
            skipped_urls[link] = reason

    crawl_duration = time.time() - start_time
    audit_report = CrawlAuditReport(
        seed_url=clean_url,
        discovered_urls=len(all_discovered_links) + len(pages),
        eligible_urls=len(eligible_links) + len(pages),
        crawled_urls=len(pages),
        stored_documents=len(pages),
        chunked_documents=0,
        total_chunks=0,
        embedded_chunks=0,
        duplicate_urls_removed=duplicate_count,
        canonical_urls=canonical_count,
        max_depth_reached=max_depth_seen,
        crawl_duration_seconds=crawl_duration,
        skipped_urls=skipped_urls,
        discovered_list=sorted(all_discovered_links),
        eligible_list=sorted(eligible_links),
        crawled_list=[p.url for p in pages],
    )

    return pages, audit_report


def crawl_website(
    url: str,
    max_pages: int | None = None,
    max_depth: int | None = None,
    timeout: int | None = None,
    return_audit: bool = False,
    cancel_check: Callable[[], bool] | None = None,
) -> list[Page] | tuple[list[Page], CrawlAuditReport]:
    """
    Crawls a website using Firecrawl API and returns a list of Page objects.
    Maintains backwards compatibility with existing Phase 9 signatures.
    """
    pages, audit = crawl_website_with_audit(
        url,
        max_pages=max_pages,
        max_depth=max_depth,
        timeout=timeout,
        cancel_check=cancel_check,
    )
    return (pages, audit) if return_audit else pages
