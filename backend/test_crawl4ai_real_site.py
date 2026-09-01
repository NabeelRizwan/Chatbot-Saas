import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure backend root is on sys.path
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from services.crawl4ai_service import Page, crawl_website, crawl_single_page


def run_real_site_test():
    test_url = "https://docs.python.org/3/"
    max_pages = 20
    max_depth = 2

    print(f"Initiating Crawl4AI real website crawl on: {test_url} (max_pages={max_pages}, max_depth={max_depth})...")
    pages: list[Page] = crawl_website(test_url, max_pages=max_pages, max_depth=max_depth, verbose_diagnostics=True)

    # Compute metrics
    total_pages = len(pages)
    successful_pages = sum(1 for p in pages if p.status == "success" and p.markdown)
    failed_pages = total_pages - successful_pages

    total_md_chars = sum(len(p.markdown) for p in pages if p.markdown)
    total_md_words = sum(len(p.markdown.split()) for p in pages if p.markdown)
    total_html_chars = sum(len(p.html) for p in pages if p.html)
    total_links = sum(len(p.links) for p in pages)

    avg_md_chars = int(total_md_chars / successful_pages) if successful_pages > 0 else 0
    avg_words = int(total_md_words / successful_pages) if successful_pages > 0 else 0

    print("\n==================================================")
    print("CONTENT SAMPLES (FIRST 3 PAGES)")
    print("==================================================\n")

    for idx, page in enumerate(pages[:3], start=1):
        print(f"Sample {idx}: {page.url}")
        print(f"Title: {page.title}")
        print(f"Preview:\n{page.markdown[:300]}...\n")
        print("--------------------------------------------------\n")

    print("==================================================")
    print("RESILIENCE TEST (INVALID URL HANDLING)")
    print("==================================================\n")

    unreachable_url = "https://docs.python.org/3/this-page-definitely-does-not-exist-404.html"
    print(f"Testing individual 404/unreachable URL: {unreachable_url}...")
    resilience_page = crawl_single_page(unreachable_url)
    print(f"Resilience Result -> Status: {resilience_page.status}, Code: {resilience_page.status_code}, Error: {resilience_page.error}")
    print("Confirmed: Single page failure does not raise an unhandled exception or crash the process.\n")

    print("==================================================")
    print("PHASE 6 VALIDATION RESULT")
    print("==================================================")

    # Validation criteria: at least 15 pages returned, all having substantive markdown content
    passed = (
        total_pages >= 15
        and successful_pages == total_pages
        and total_md_chars > 50000
        and all(isinstance(p, Page) for p in pages)
    )

    if passed:
        print("\nPASS\n")
    else:
        print("\nFAIL\n")

    print("==================================================")
    return passed


if __name__ == "__main__":
    success = run_real_site_test()
    sys.exit(0 if success else 1)
