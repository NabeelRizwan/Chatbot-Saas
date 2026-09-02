"""Crawler port and provider registry used by knowledge ingestion."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass
class CrawlPage:
    requested_url: str
    canonical_url: str
    title: str
    markdown: str
    metadata: dict[str, Any] = field(default_factory=dict)
    links: list[str] = field(default_factory=list)
    status: str = "ready"

    @property
    def url(self) -> str:
        """Backward-compatible application URL identity."""
        return self.canonical_url or self.requested_url


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
    provider: str = "unknown"


class CrawlerProvider(Protocol):
    provider_name: str

    def crawl_site(
        self,
        url: str,
        *,
        max_pages: int | None = None,
        max_depth: int | None = None,
        timeout: int | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[list[CrawlPage], CrawlAuditReport]: ...

    def fetch_exact_page(
        self,
        url: str,
        *,
        timeout: int | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[list[CrawlPage], CrawlAuditReport]: ...

    def cancel(self, provider_job_id: str) -> bool: ...


class FirecrawlCrawlerProvider:
    provider_name = "firecrawl"

    @staticmethod
    def _normalize_pages(pages) -> list[CrawlPage]:
        normalized: list[CrawlPage] = []
        for page in pages:
            metadata = dict(getattr(page, "metadata", None) or {})
            requested_url = str(getattr(page, "url", "") or "")
            canonical_url = str(
                metadata.get("canonical_url")
                or metadata.get("canonicalURL")
                or requested_url
            )
            metadata.setdefault("requested_url", requested_url)
            metadata.setdefault("canonical_url", canonical_url)
            normalized.append(
                CrawlPage(
                    requested_url=requested_url,
                    canonical_url=canonical_url,
                    title=str(getattr(page, "title", "") or canonical_url),
                    markdown=str(getattr(page, "markdown", "") or ""),
                    metadata=metadata,
                    links=list(getattr(page, "links", None) or []),
                )
            )
        return normalized

    def crawl_site(self, url: str, **kwargs):
        from services.firecrawl_service import crawl_website_with_audit
        pages, audit = crawl_website_with_audit(url, **kwargs)
        audit.provider = self.provider_name
        return self._normalize_pages(pages), audit

    def fetch_exact_page(self, url: str, **kwargs):
        from services.firecrawl_service import scrape_single_page_with_audit
        pages, audit = scrape_single_page_with_audit(url, **kwargs)
        audit.provider = self.provider_name
        return self._normalize_pages(pages), audit

    def cancel(self, provider_job_id: str) -> bool:
        from services.firecrawl_service import cancel_firecrawl_crawl
        return cancel_firecrawl_crawl(provider_job_id)


def get_crawler_provider(provider_name: str | None = None) -> CrawlerProvider:
    selected = (provider_name or os.getenv("CRAWLER_PROVIDER") or "firecrawl").lower().strip()
    if selected == "firecrawl":
        return FirecrawlCrawlerProvider()
    raise RuntimeError(f"Unsupported crawler provider '{selected}'. Firecrawl is the active adapter.")
