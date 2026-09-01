import asyncio
import re
import sys
from pathlib import Path

# Ensure backend root is on sys.path
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

import crawl4ai
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig


def get_crawl4ai_version() -> str:
    try:
        import crawl4ai.__version__ as v
        return getattr(v, "__version__", "0.9.2")
    except Exception:
        return getattr(crawl4ai, "__version__", "0.9.2")


async def run_proof_of_life():
    url = "https://example.com"
    version = get_crawl4ai_version()

    success = False
    status_code = "Unknown"
    page_title = "Unknown"
    markdown_chars = 0
    markdown_words = 0
    links_count = 0
    markdown_preview = ""
    error_message = None

    try:
        browser_config = BrowserConfig(headless=True)
        run_config = CrawlerRunConfig()

        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=run_config)

            success = bool(getattr(result, "success", False))
            status_code = getattr(result, "status_code", "Unknown")

            # Extract markdown
            raw_markdown = str(result.markdown or "") if result.markdown else ""
            markdown_chars = len(raw_markdown)
            markdown_words = len(raw_markdown.split()) if raw_markdown else 0
            markdown_preview = raw_markdown[:1000]

            # Extract page title
            metadata = getattr(result, "metadata", {}) or {}
            if isinstance(metadata, dict) and metadata.get("title"):
                page_title = metadata.get("title")
            else:
                # Fallback to H1 search in markdown
                match = re.search(r"^#\s+(.+)$", raw_markdown, re.MULTILINE)
                if match:
                    page_title = match.group(1).strip()

            # Extract links count
            links = getattr(result, "links", {})
            if isinstance(links, dict):
                internal = links.get("internal", []) or []
                external = links.get("external", []) or []
                links_count = len(internal) + len(external)
            elif isinstance(links, list):
                links_count = len(links)

            if not success and getattr(result, "error_message", None):
                error_message = result.error_message

    except Exception as exc:
        success = False
        error_message = str(exc)

    # Print required diagnostic report
    print("\n==================================================")
    print("========== CRAWL4AI PROOF OF LIFE ==========")
    print("==================================================\n")
    print(f"Crawl4AI Version:\n{version}\n")
    print(f"URL:\n{url}\n")
    print(f"Success:\n{str(success).lower()}\n")
    print(f"Status Code:\n{status_code}\n")
    print(f"Page Title:\n{page_title}\n")
    print(f"Markdown Characters:\n{markdown_chars}\n")
    print(f"Markdown Words:\n{markdown_words}\n")
    print(f"Links Discovered:\n{links_count}\n")
    print(f"Markdown Preview:\n{markdown_preview}\n")
    print("==================================================")
    print("RESULT")
    print("==================================================\n")

    if success and markdown_chars > 0:
        print("SUCCESS\n")
    else:
        print("FAILED\n")
        if error_message:
            print(f"Error Details: {error_message}\n")

    print("==================================================")
    return success and markdown_chars > 0


if __name__ == "__main__":
    passed = asyncio.run(run_proof_of_life())
    sys.exit(0 if passed else 1)
