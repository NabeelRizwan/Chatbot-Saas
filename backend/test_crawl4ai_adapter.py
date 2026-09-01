import sys
import unittest
from pathlib import Path

# Ensure backend root is on sys.path
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from services.crawl4ai_service import (
    Crawl4AIError,
    Page,
    crawl_single_page,
    crawl_website,
    extract_title_from_markdown,
    get_crawler_config,
    print_adapter_diagnostic,
    validate_crawl_url,
)


class TestCrawl4AIAdapter(unittest.TestCase):

    def test_validate_crawl_url(self):
        # Valid URLs
        self.assertEqual(validate_crawl_url("https://example.com"), "https://example.com")
        self.assertEqual(validate_crawl_url("http://example.org/docs"), "http://example.org/docs")

        # Invalid URLs
        with self.assertRaises(Crawl4AIError):
            validate_crawl_url("ftp://example.com")
        with self.assertRaises(Crawl4AIError):
            validate_crawl_url("not-a-url")
        with self.assertRaises(Crawl4AIError):
            validate_crawl_url("http://127.0.0.1")

    def test_extract_title_from_markdown(self):
        md = "# My Document Title\n\nSome paragraph text."
        self.assertEqual(extract_title_from_markdown(md, "Default"), "My Document Title")

        md_no_h1 = "Just paragraph text without h1 header."
        self.assertEqual(extract_title_from_markdown(md_no_h1, "Default"), "Default")

    def test_crawl_adapter_example_com(self):
        test_url = "https://example.com"
        page = crawl_single_page(test_url)

        # 1. Page object returned
        self.assertIsInstance(page, Page)

        # 2. URL exists and matches
        self.assertIn(page.url, (test_url, f"{test_url}/"))

        # 3. Title exists
        self.assertTrue(bool(page.title))
        self.assertEqual(page.title, "Example Domain")

        # 4. Markdown exists and is non-empty
        self.assertTrue(bool(page.markdown))
        self.assertIn("Example Domain", page.markdown)

        # 5. HTML is handled
        self.assertTrue(bool(page.html))
        self.assertIn("<html", page.html.lower())

        # 6. Metadata is handled
        self.assertIsInstance(page.metadata, dict)

        # 7. Links are returned
        self.assertIsInstance(page.links, list)
        self.assertGreaterEqual(len(page.links), 1)
        self.assertTrue(any("iana.org" in link for link in page.links))

        # 8. Status is returned
        self.assertEqual(page.status, "success")
        self.assertEqual(page.status_code, 200)
        self.assertIsNone(page.error)

        # 9. Print diagnostic output
        print_adapter_diagnostic(page)

    def test_crawl_website_wrapper_returns_page_list(self):
        test_url = "https://example.com"
        pages = crawl_website(test_url, verbose_diagnostics=False)

        self.assertIsInstance(pages, list)
        self.assertEqual(len(pages), 1)
        self.assertIsInstance(pages[0], Page)
        self.assertIn(pages[0].url, (test_url, f"{test_url}/"))
        self.assertEqual(pages[0].status, "success")

    def test_extract_cta_links_from_html(self):
        from services.crawl4ai_service import extract_cta_links_from_html

        sample_html = """
        <div class="product">
          <h2>NovaPhone Ultra 15</h2>
          <p>Price: $999</p>
          <a href="/cart/add?id=99" class="btn">Add to Cart</a>
          <a href="/checkout" class="btn">Buy Now</a>
          <button data-href="https://store.example.com/order" title="Order Now">Order Now</button>
          <a href="https://example.com/contact" class="link">Contact Us</a>
          <a href="/docs/guide">Regular Docs Link</a>
        </div>
        """
        source_url = "https://example.com/products/novaphone"
        ctas = extract_cta_links_from_html(sample_html, source_url)

        self.assertEqual(len(ctas), 4)

        # Check Add to Cart
        cta_cart = next((c for c in ctas if "Add to Cart" in c["text"]), None)
        self.assertIsNotNone(cta_cart)
        self.assertEqual(cta_cart["url"], "https://example.com/cart/add?id=99")
        self.assertEqual(cta_cart["source_url"], source_url)
        self.assertEqual(cta_cart["type"], "a")
        self.assertTrue(cta_cart["is_internal"])
        self.assertEqual(cta_cart["context"], "NovaPhone Ultra 15")

        # Check Buy Now
        cta_buy = next((c for c in ctas if "Buy Now" in c["text"]), None)
        self.assertIsNotNone(cta_buy)
        self.assertEqual(cta_buy["url"], "https://example.com/checkout")

        # Check Order Now button
        cta_order = next((c for c in ctas if "Order Now" in c["text"]), None)
        self.assertIsNotNone(cta_order)
        self.assertEqual(cta_order["url"], "https://store.example.com/order")
        self.assertEqual(cta_order["type"], "button")

        # Check Contact Us
        cta_contact = next((c for c in ctas if "Contact Us" in c["text"]), None)
        self.assertIsNotNone(cta_contact)
        self.assertEqual(cta_contact["url"], "https://example.com/contact")

    def test_is_safe_crawl_url_excludes_stateful_pages(self):
        from services.crawl4ai_service import is_safe_crawl_url

        # Safe URLs
        self.assertTrue(is_safe_crawl_url("https://example.com/products/novaphone"))
        self.assertTrue(is_safe_crawl_url("https://example.com/docs/intro"))
        self.assertTrue(is_safe_crawl_url("https://example.com/about-us"))

        # Stateful / Auth / Session URLs (must be excluded from normal content crawl queue)
        self.assertFalse(is_safe_crawl_url("https://example.com/cart"))
        self.assertFalse(is_safe_crawl_url("https://example.com/checkout"))
        self.assertFalse(is_safe_crawl_url("https://example.com/login"))
        self.assertFalse(is_safe_crawl_url("https://example.com/logout"))
        self.assertFalse(is_safe_crawl_url("https://example.com/auth/callback"))
        self.assertFalse(is_safe_crawl_url("https://example.com/admin/settings"))
        self.assertFalse(is_safe_crawl_url("https://example.com/page?sessionid=abc12345"))

    def test_parse_sitemap_xml(self):
        from services.crawl4ai_service import parse_sitemap_xml

        # Standard sitemap
        xml_urlset = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/page-1</loc></url>
          <url><loc>https://example.com/page-2</loc></url>
        </urlset>"""
        pages, child_sm = parse_sitemap_xml(xml_urlset)
        self.assertEqual(len(pages), 2)
        self.assertIn("https://example.com/page-1", pages)
        self.assertEqual(len(child_sm), 0)

        # Sitemap index
        xml_index = """<?xml version="1.0" encoding="UTF-8"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>https://example.com/sitemap-products.xml</loc></sitemap>
          <sitemap><loc>https://example.com/sitemap-blogs.xml</loc></sitemap>
        </sitemapindex>"""
        pages_idx, child_sm_idx = parse_sitemap_xml(xml_index)
        self.assertEqual(len(pages_idx), 0)
        self.assertEqual(len(child_sm_idx), 2)
        self.assertIn("https://example.com/sitemap-products.xml", child_sm_idx)

    def test_normalize_child_url_tracking_params_and_sorting(self):
        from services.crawl4ai_service import normalize_child_url

        # Strips tracking params but preserves content params
        url_with_tracking = "https://example.com/product?utm_source=google&id=123&fbclid=xyz&category=phones"
        normalized = normalize_child_url(url_with_tracking, "https://example.com")
        self.assertEqual(normalized, "https://example.com/product?category=phones&id=123")

        # Strips fragments
        url_with_frag = "https://example.com/docs/intro#section-2"
        normalized_frag = normalize_child_url(url_with_frag, "https://example.com")
        self.assertEqual(normalized_frag, "https://example.com/docs/intro")

    def test_extract_rich_metadata_canonical_and_json_ld(self):
        from services.crawl4ai_service import extract_rich_metadata_from_html

        sample_html = """
        <html>
          <head>
            <link rel="canonical" href="https://example.com/canonical-page" />
            <script type="application/ld+json">
            {
              "@context": "https://schema.org",
              "@type": "Product",
              "name": "NovaPhone Pro",
              "offers": {
                "@type": "Offer",
                "price": "899"
              }
            }
            </script>
          </head>
          <body><h1>Product</h1></body>
        </html>
        """
        meta = extract_rich_metadata_from_html(sample_html, "https://example.com/page")
        self.assertEqual(meta.get("canonical_url"), "https://example.com/canonical-page")
        self.assertIn("json_ld", meta)
        self.assertEqual(meta["json_ld"][0]["name"], "NovaPhone Pro")


if __name__ == "__main__":
    unittest.main()
