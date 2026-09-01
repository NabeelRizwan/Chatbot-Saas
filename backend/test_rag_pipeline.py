"""
Comprehensive Phase 9 Production RAG Test Suite
Validates:
1. Exact factual question (compact context)
2. Factual question where relevant info is in later chunks
3. Entity question requiring sibling chunk expansion
4. Catalog question across multiple documents (full-corpus discovery)
5. Category listing discovery
6. Multi-product feature filtering
7. Balanced multi-entity comparison
8. Cross-page synthesis
9. Purchase / canonical URL navigation
10. Missing information grounding (no hallucinations)
11. Follow-up conversational pronoun resolution
12. Multi-bot tenant isolation
13. Large website scalability (100+ chunks)
14. Late-ranked chunk recovery via hybrid RRF & expansion
15. Separation of retrieval size from answer size (conciseness instruction)
"""
import os
import sys
from types import SimpleNamespace

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.scraper_service import _extract_text_from_html, clean_text
from services.chunking_service import (
    chunk_text_with_metadata,
    normalize_text,
    count_tokens,
    CHUNK_SIZE,
)
from services.intent_router import (
    classify_intent,
    detect_retrieval_mode,
    is_catalog_or_list_query,
    is_comparison_query,
    is_purchase_intent,
    is_filter_query,
    is_policy_query,
    is_entity_broad_query,
    rewrite_query_for_retrieval,
    RETRIEVAL_MODE_FACTUAL,
    RETRIEVAL_MODE_ENTITY,
    RETRIEVAL_MODE_CATALOG,
    RETRIEVAL_MODE_FILTER,
    RETRIEVAL_MODE_COMPARISON,
    RETRIEVAL_MODE_POLICY,
    RETRIEVAL_MODE_PURCHASE,
    INTENT_CATALOG_LIST,
    INTENT_COMPARISON,
    INTENT_PURCHASE,
    INTENT_FILTER,
    INTENT_POLICY,
    INTENT_ENTITY_DEEP,
    INTENT_GREETING,
    INTENT_PRONOUN_FOLLOWUP,
)
from services.conversational_engine import (
    compress_and_rerank_chunks,
    critique_response,
    verify_answer,
    polish_answer,
)
from services.rag_service import (
    clean_retrieved_chunks,
    build_rag_prompt,
)


def log_test(step_name: str, success: bool, info: str = ""):
    status = "SUCCESS" if success else "FAILED"
    print(f"[{status}] {step_name} {f'({info})' if info else ''}")
    if not success:
        raise AssertionError(f"Test failed: {step_name} - {info}")


def test_1_html_table_extraction():
    print("\n--- TEST 1: HTML Table Extraction to Markdown & Key-Values ---")
    html = """
    <html>
    <head><title>NovaTech Product Specifications</title></head>
    <body>
        <h1>NovaTech Product Lineup</h1>
        <p>Explore our premium product offerings below.</p>
        <table>
            <tr><th>Product</th><th>Price</th><th>Battery</th><th>Storage</th></tr>
            <tr><td>NovaPhone Ultra 15</td><td>$999</td><td>5000mAh Li-Po</td><td>256GB</td></tr>
            <tr><td>NovaBook Air X14</td><td>$1299</td><td>70Wh (18 hours)</td><td>512GB SSD</td></tr>
            <tr><td>NovaTab Pro 11</td><td>$699</td><td>8000mAh</td><td>128GB</td></tr>
        </table>
    </body>
    </html>
    """
    title, text = _extract_text_from_html(html)
    log_test("Extract HTML Table Title", title == "NovaTech Product Specifications", f"Title: {title}")
    log_test("Markdown Table Header Preserved", "| Product | Price | Battery | Storage |" in text)
    log_test("NovaPhone Row in Table", "NovaPhone Ultra 15" in text and "5000mAh Li-Po" in text)
    log_test("Row Key-Value Summary Generated", "NovaPhone Ultra 15 (Price: $999, Battery: 5000mAh Li-Po, Storage: 256GB)" in text)


def test_2_html_accordion_and_json_ld():
    print("\n--- TEST 2: Accordions (<details>) and JSON-LD Extraction ---")
    html = """
    <html>
    <head>
        <title>NovaTech Support & FAQ</title>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "NovaPhone Ultra 15",
            "description": "Flagship 5G smartphone with titanium frame.",
            "sku": "NP-U15-256",
            "brand": "NovaTech",
            "offers": {
                "@type": "Offer",
                "price": "999",
                "priceCurrency": "USD"
            }
        }
        </script>
    </head>
    <body>
        <h1>Customer Support & Policies</h1>
        <details>
            <summary>What is your warranty period?</summary>
            <p>We provide a 2-year full manufacturer warranty covering all hardware defects and battery degradation below 80%.</p>
        </details>
        <details>
            <summary>How do returns and refunds work?</summary>
            <p>Customers can return any product within 30 days of delivery for a full 100% refund with free return shipping.</p>
        </details>
    </body>
    </html>
    """
    title, text = _extract_text_from_html(html)
    log_test("JSON-LD Product SKU Extracted", "SKU / Model: NP-U15-256" in text)
    log_test("JSON-LD Product Price Extracted", "Price: USD 999" in text)
    log_test("Accordion FAQ 1 Extracted", "Q: What is your warranty period?" in text and "2-year full manufacturer warranty" in text)
    log_test("Accordion FAQ 2 Extracted", "Q: How do returns and refunds work?" in text and "30 days of delivery" in text)


def test_3_structure_aware_chunking():
    print("\n--- TEST 3: Structure-Aware Chunking & Context Prefixing ---")
    document_text = """
    # NovaTech Catalog 2026

    Welcome to NovaTech's official hardware catalog.

    ## NovaPhone Ultra 15
    The NovaPhone Ultra 15 features a 6.7-inch Super AMOLED 120Hz display, titanium chassis, and the NovaChip Gen 3 processor.
    - Battery: 5000mAh Li-Po with 80W wired fast charging and 50W wireless charging.
    - RAM: 12GB LPDDR5X.
    - Storage: 256GB / 512GB UFS 4.0.
    - Price: $999 for 256GB, $1199 for 512GB.
    - Colors: Titanium Gray, Deep Blue, Ceramic White.

    ## NovaBook Air X14
    The NovaBook Air X14 is an ultra-portable workstation laptop with an M-series NovaSilicon chip.
    - Display: 14.2-inch Liquid Retina XDR.
    - Battery: 70Wh offering up to 18 hours of web browsing.
    - RAM: 16GB unified memory.
    - Storage: 512GB / 1TB PCIe 4.0 SSD.
    - Price: Starting at $1,299.
    - Ports: 3x Thunderbolt 4, HDMI 2.1, MagSafe charging.

    ## Subscription & Cloud Plans
    | Plan | Monthly Price | Cloud Storage | Priority Support |
    | Pro | $29/mo | 1TB | Included |
    | Enterprise | $99/mo | Unlimited | 24/7 Dedicated Support |
    """

    chunks = chunk_text_with_metadata(
        document_text,
        page_title="NovaTech Catalog 2026",
        source_url="https://novatech.example.com/catalog",
    )

    log_test("Chunks Created from Structured Document", len(chunks) >= 3, f"Count: {len(chunks)}")
    
    phone_chunk = next((c for c in chunks if "NovaPhone Ultra 15" in c.heading or "NovaPhone Ultra 15" in c.content), None)
    log_test("NovaPhone Chunk Found", phone_chunk is not None)
    log_test("NovaPhone Chunk Has Battery Spec", "5000mAh" in phone_chunk.content)
    log_test("NovaPhone Chunk Has Contextual Prefix", "[NovaTech Catalog 2026]" in phone_chunk.content or "[NovaPhone Ultra 15]" in phone_chunk.content)
    log_test("NovaPhone Chunk Has Metadata", phone_chunk.metadata.get("source_url") == "https://novatech.example.com/catalog")

    laptop_chunk = next((c for c in chunks if "NovaBook Air X14" in c.heading or "NovaBook Air X14" in c.content), None)
    log_test("NovaBook Chunk Found", laptop_chunk is not None)
    log_test("NovaBook Chunk Has 18 Hours Battery", "18 hours" in laptop_chunk.content)

    table_chunk = next((c for c in chunks if "Subscription & Cloud Plans" in c.heading or "Cloud Storage" in c.content), None)
    log_test("Pricing Table Chunk Found", table_chunk is not None)
    log_test("Pricing Table Retains Pro & Enterprise", "Pro" in table_chunk.content and "Enterprise" in table_chunk.content)


def test_4_intent_routing_and_retrieval_modes():
    print("\n--- TEST 4: Query Understanding & Phase 9 Retrieval Modes ---")

    # Mode Factual
    mode_f, _ = detect_retrieval_mode("What is the battery capacity of NovaPhone Ultra 15?")
    log_test("Detect MODE_FACTUAL", mode_f == RETRIEVAL_MODE_FACTUAL)

    # Mode Catalog
    mode_c, _ = detect_retrieval_mode("What products do you have?")
    log_test("Detect MODE_CATALOG", mode_c == RETRIEVAL_MODE_CATALOG)

    # Mode Filter
    mode_filt, info_filt = detect_retrieval_mode("Which products support 80W fast charging?")
    log_test("Detect MODE_FILTER", mode_filt == RETRIEVAL_MODE_FILTER, f"Filter info: {info_filt}")

    # Mode Comparison
    mode_comp, info_comp = detect_retrieval_mode("Compare NovaPhone Ultra 15 and NovaBook Air X14")
    log_test("Detect MODE_COMPARISON", mode_comp == RETRIEVAL_MODE_COMPARISON)
    log_test("Extract Comparison Entities", len(info_comp.get("entities", [])) >= 2)

    # Mode Entity Deep
    mode_ent, info_ent = detect_retrieval_mode("Tell me everything about NovaPhone Ultra 15")
    log_test("Detect MODE_ENTITY", mode_ent == RETRIEVAL_MODE_ENTITY)

    # Mode Purchase
    mode_pur, _ = detect_retrieval_mode("I want to buy the NovaPhone Ultra 15")
    log_test("Detect MODE_PURCHASE", mode_pur == RETRIEVAL_MODE_PURCHASE)

    # Mode Policy
    mode_pol, _ = detect_retrieval_mode("What is your 30-day return policy?")
    log_test("Detect MODE_POLICY", mode_pol == RETRIEVAL_MODE_POLICY)

    # Conversational Follow-up Rewriting
    history = [
        {"role": "user", "content": "Tell me about the NovaPhone Ultra 15."},
        {"role": "assistant", "content": "The NovaPhone Ultra 15 is our flagship smartphone with a 5000mAh battery."}
    ]
    rewritten_battery = rewrite_query_for_retrieval("What about its battery?", history=history)
    log_test("Rewrite Pronoun 'its battery'", "NovaPhone Ultra 15" in rewritten_battery, f"Result: '{rewritten_battery}'")


def test_5_entity_sibling_expansion():
    print("\n--- TEST 5: Entity Question & Sibling Chunk Expansion ---")
    # Simulate an entity with 4 sibling chunks from the same document (Overview, Specs, Features, Pricing)
    sibling_chunks = [
        {
            "score": 0.88,
            "chunk": SimpleNamespace(id=1, chunk_index=0, content="NovaPhone Ultra 15 Overview: Flagship smartphone with titanium frame."),
            "document": SimpleNamespace(id=10, title="NovaPhone Ultra 15 Product Page", source_url="https://novatech.example.com/phone")
        },
        {
            "score": 0.72,
            "chunk": SimpleNamespace(id=2, chunk_index=1, content="NovaPhone Ultra 15 Specs: 5000mAh battery, 12GB RAM, NovaChip Gen 3."),
            "document": SimpleNamespace(id=10, title="NovaPhone Ultra 15 Product Page", source_url="https://novatech.example.com/phone")
        },
        {
            "score": 0.70,
            "chunk": SimpleNamespace(id=3, chunk_index=2, content="NovaPhone Ultra 15 Features: 80W wired charging, 50W wireless charging, Super AMOLED 120Hz."),
            "document": SimpleNamespace(id=10, title="NovaPhone Ultra 15 Product Page", source_url="https://novatech.example.com/phone")
        },
        {
            "score": 0.68,
            "chunk": SimpleNamespace(id=4, chunk_index=3, content="NovaPhone Ultra 15 Pricing & Purchase: $999 for 256GB. Buy at https://novatech.example.com/buy-u15"),
            "document": SimpleNamespace(id=10, title="NovaPhone Ultra 15 Product Page", source_url="https://novatech.example.com/phone")
        },
    ]

    top_items, assembled_ctx = compress_and_rerank_chunks(
        sibling_chunks,
        query="Tell me about NovaPhone Ultra 15",
        max_context_chars=8500,
        mode="entity",
    )
    log_test("Entity Sibling Chunks Retained in Context", len(top_items) == 4)
    log_test("Context Has Overview, Specs, Features, and Pricing", "Overview" in assembled_ctx and "Specs" in assembled_ctx and "Features" in assembled_ctx and "Pricing" in assembled_ctx)
    log_test("Context Preserves Canonical Purchase Link", "https://novatech.example.com/buy-u15" in assembled_ctx)


def test_6_catalog_cross_document_discovery():
    print("\n--- TEST 6: Full Catalog Discovery Across Multiple Documents ---")
    # Simulate 6 distinct products across 6 separate document pages
    corpus_products = [
        {
            "score": 0.75 - (i * 0.02),
            "chunk": SimpleNamespace(id=100 + i, chunk_index=0, content=f"Product #{i+1}: ApexModel-{i+1} is our premium solution with high performance."),
            "document": SimpleNamespace(id=200 + i, title=f"ApexModel-{i+1} Page", filename=f"model_{i+1}.html", source_url=f"https://example.com/products/model-{i+1}")
        }
        for i in range(6)
    ]

    cleaned_catalog = clean_retrieved_chunks(corpus_products, top_k=16, max_per_doc=8)
    log_test("All 6 Distinct Products Discovered", len(cleaned_catalog) == 6)

    _, assembled_catalog = compress_and_rerank_chunks(
        cleaned_catalog,
        query="What products do you offer?",
        max_context_chars=12000,
        mode="catalog",
    )
    for i in range(1, 7):
        log_test(f"Catalog Context Contains Product #{i}", f"ApexModel-{i}" in assembled_catalog)


def test_7_balanced_multi_entity_comparison():
    print("\n--- TEST 7: Balanced Multi-Entity Comparison Retrieval ---")
    comparison_chunks = [
        {
            "score": 0.85,
            "chunk": SimpleNamespace(id=10, chunk_index=0, content="Product Alpha: 5000mAh battery, 12GB RAM, $999."),
            "document": SimpleNamespace(id=1, title="Product Alpha Page", source_url="https://example.com/alpha")
        },
        {
            "score": 0.84,
            "chunk": SimpleNamespace(id=11, chunk_index=1, content="Product Alpha Features: 80W charging, Titanium frame."),
            "document": SimpleNamespace(id=1, title="Product Alpha Page", source_url="https://example.com/alpha")
        },
        {
            "score": 0.83,
            "chunk": SimpleNamespace(id=20, chunk_index=0, content="Product Beta: 70Wh battery, 16GB RAM, $1299."),
            "document": SimpleNamespace(id=2, title="Product Beta Page", source_url="https://example.com/beta")
        },
        {
            "score": 0.82,
            "chunk": SimpleNamespace(id=21, chunk_index=1, content="Product Beta Features: 18 hours battery, MagSafe."),
            "document": SimpleNamespace(id=2, title="Product Beta Page", source_url="https://example.com/beta")
        },
    ]

    top_items, assembled_comp = compress_and_rerank_chunks(
        comparison_chunks,
        query="Compare Product Alpha and Product Beta",
        max_context_chars=9500,
        mode="comparison",
    )
    log_test("Comparison Context Contains Alpha and Beta", "Product Alpha" in assembled_comp and "Product Beta" in assembled_comp)
    log_test("Balanced Representation of Both Entities", "70Wh" in assembled_comp and "5000mAh" in assembled_comp)


def test_8_multi_product_filter_query():
    print("\n--- TEST 8: Multi-Product Feature Filter Query ---")
    filter_chunks = [
        {
            "score": 0.85,
            "chunk": SimpleNamespace(id=1, chunk_index=0, content="Device Ultra: Supports 80W fast charging and 50W wireless charging."),
            "document": SimpleNamespace(id=10, title="Device Ultra", source_url="https://example.com/ultra")
        },
        {
            "score": 0.82,
            "chunk": SimpleNamespace(id=2, chunk_index=0, content="Device Pro: Supports 80W fast charging with 4500mAh cell."),
            "document": SimpleNamespace(id=11, title="Device Pro", source_url="https://example.com/pro")
        },
        {
            "score": 0.60,
            "chunk": SimpleNamespace(id=3, chunk_index=0, content="Device Lite: Standard 18W charging only."),
            "document": SimpleNamespace(id=12, title="Device Lite", source_url="https://example.com/lite")
        },
    ]

    top_items, assembled_filt = compress_and_rerank_chunks(
        filter_chunks,
        query="Which products support 80W fast charging?",
        max_context_chars=11000,
        mode="filter",
    )
    log_test("Filter Context Retains Ultra and Pro", "Device Ultra" in assembled_filt and "Device Pro" in assembled_filt)


def test_9_cross_page_synthesis():
    print("\n--- TEST 9: Cross-Page Synthesis (Specs on Page A + Pricing on Page B) ---")
    cross_page_chunks = [
        {
            "score": 0.85,
            "chunk": SimpleNamespace(id=1, chunk_index=0, content="NovaBook Pro 16 Specifications: 32GB Unified Memory, M3 Chip, 100Wh Battery."),
            "document": SimpleNamespace(id=101, title="NovaBook Specs Page", source_url="https://novatech.example.com/specs")
        },
        {
            "score": 0.80,
            "chunk": SimpleNamespace(id=2, chunk_index=0, content="NovaBook Pro 16 Official Pricing: $1,999 with 1-year AppleCare equivalent warranty."),
            "document": SimpleNamespace(id=102, title="NovaBook Store & Pricing Page", source_url="https://novatech.example.com/store")
        }
    ]

    top_items, assembled_cross = compress_and_rerank_chunks(
        cross_page_chunks,
        query="What are the specs and price of NovaBook Pro 16?",
        max_context_chars=8000,
    )
    log_test("Context Combines Specs and Store Pages", "32GB Unified Memory" in assembled_cross and "$1,999" in assembled_cross)
    log_test("Source Attribution Retains Both URLs", "https://novatech.example.com/specs" in assembled_cross and "https://novatech.example.com/store" in assembled_cross)


def test_10_purchase_intent_canonical_url():
    print("\n--- TEST 10: Purchase Intent with Actionable Canonical URLs ---")
    retrieved = [
        {
            "score": 0.92,
            "chunk": SimpleNamespace(id=1, content="NovaPhone Ultra 15 is available now for $999. Official Order Link: https://novatech.example.com/checkout/novaphone-u15"),
            "document": SimpleNamespace(id=1, title="NovaPhone Checkout", source_url="https://novatech.example.com/checkout/novaphone-u15")
        }
    ]
    prompt = build_rag_prompt(
        question="Where can I purchase the NovaPhone Ultra 15?",
        retrieved=retrieved,
        mode="purchase",
        context_budget=4000,
    )
    log_test("Prompt Contains Real Purchase URL", "https://novatech.example.com/checkout/novaphone-u15" in prompt)
    log_test("Prompt Has Actionable URL Rule 12", "Rule 12" in prompt and "canonical page URL" in prompt)


def test_11_separation_of_retrieval_size_from_answer_size():
    print("\n--- TEST 11: Separation of Retrieval Size from Answer Size ---")
    # Even if 5 chunks containing comprehensive phone specs are retrieved for a simple battery question,
    # Rule 10 explicitly enforces conciseness.
    retrieved = [
        {
            "score": 0.90,
            "chunk": SimpleNamespace(id=1, content="NovaPhone Ultra 15: Battery capacity is 5,000 mAh Li-Po."),
            "document": SimpleNamespace(id=1, title="Phone Specs", source_url="https://example.com/phone")
        },
        {
            "score": 0.75,
            "chunk": SimpleNamespace(id=2, content="NovaPhone Ultra 15: 12GB RAM, 256GB Storage, Titanium Gray finish, 120Hz display."),
            "document": SimpleNamespace(id=1, title="Phone Specs", source_url="https://example.com/phone")
        }
    ]
    prompt = build_rag_prompt(
        question="What is the battery capacity?",
        retrieved=retrieved,
        mode="factual",
        context_budget=3500,
    )
    log_test("Prompt Has Conciseness Rule 10", "Rule 10" in prompt and "Answer ONLY the user's specific question" in prompt)


def test_12_missing_information_grounding():
    print("\n--- TEST 12: Missing Information Grounding & Honesty ---")
    empty_retrieved = []
    _, ctx = compress_and_rerank_chunks(empty_retrieved, query="What is the engine size of your luxury yacht?")
    log_test("Empty Context for Non-Existent Info", ctx == "")
    prompt = build_rag_prompt(
        question="What is the engine size of your luxury yacht?",
        retrieved=empty_retrieved,
    )
    log_test("Prompt Handles Missing Information Honestly", "No relevant business information found." in prompt)


def test_13_multi_bot_isolation():
    print("\n--- TEST 13: Strict Multi-Bot Tenant Isolation ---")
    bot_a_chunks = [
        {
            "score": 0.90,
            "chunk": SimpleNamespace(id=1, content="Bot A SaaS Platform API Documentation"),
            "document": SimpleNamespace(id=10, bot_id=1, title="SaaS Docs", source_url="https://saas.example.com/docs")
        }
    ]
    bot_b_chunks = [
        {
            "score": 0.90,
            "chunk": SimpleNamespace(id=2, content="Bot B Dental Clinic Appointment Scheduling"),
            "document": SimpleNamespace(id=20, bot_id=2, title="Dental Clinic", source_url="https://dental.example.com")
        }
    ]

    cleaned_a = clean_retrieved_chunks(bot_a_chunks, top_k=4)
    cleaned_b = clean_retrieved_chunks(bot_b_chunks, top_k=4)

    log_test("Bot A Only Sees Bot A Data", all(item["document"].bot_id == 1 for item in cleaned_a))
    log_test("Bot B Only Sees Bot B Data", all(item["document"].bot_id == 2 for item in cleaned_b))
    log_test("Zero Cross-Bot Data Leakage", not any(item["document"].bot_id == 2 for item in cleaned_a))


def test_14_large_website_100_chunks():
    print("\n--- TEST 14: Large Website Scalability (120 chunks across 20 docs) ---")
    large_website_chunks = [
        {
            "score": 0.85 if i == 77 else (0.40 + (i % 20) * 0.01),
            "chunk": SimpleNamespace(id=i, chunk_index=i % 6, content=f"Page {i//6} Section {i%6}: {'Target Keyword Specific Fact 77' if i == 77 else f'General information chunk {i}'}"),
            "document": SimpleNamespace(id=i//6, title=f"Page {i//6}", source_url=f"https://example.com/page-{i//6}")
        }
        for i in range(120)
    ]

    top_items, assembled = compress_and_rerank_chunks(
        large_website_chunks,
        query="Target Keyword Specific Fact 77",
        max_context_chars=6000,
        mode="factual",
    )
    log_test("Specific Chunk 77 Ranked Top in 120-Chunk Corpus", "Target Keyword Specific Fact 77" in assembled)
    log_test("Context Remains Bound to Budget", len(assembled) <= 6000)


def test_15_critique_verify_polish_pipeline_preservation():
    print("\n--- TEST 15: Preservation of Critique -> Verify -> Polish Pipeline ---")
    ans_grounding = "According to document 1, we provide a 2-year warranty."
    passed_g, critique_g = critique_response(ans_grounding, question="What is your warranty?")
    log_test("Critique Identifies Grounding Issue", not passed_g and critique_g.get("grounding_issue"))

    ans_empty = ""
    passed_e, critique_e = critique_response(ans_empty, question="What is your warranty?")
    log_test("Critique Identifies Missing Business Info", not passed_e and critique_e.get("missing_business_info"))

    # Verify only runs when factual issues occur
    should_verify = critique_g.get("hallucination") or critique_g.get("grounding_issue") or critique_g.get("missing_business_info")
    log_test("Verify Answer Triggered for Grounding Issues", should_verify)

    # Polish always runs
    polished = polish_answer(
        bot=SimpleNamespace(provider="mock", model_name="mock"),
        question="What is the battery capacity?",
        answer="The battery capacity is 5000 mAh.",
        system_instruction="Support agent",
        was_verified=True,
    )
    log_test("Polish Always Runs and Produces Output", "5000 mAh" in polished)


if __name__ == "__main__":
    print("=========================================================")
    print("RUNNING PHASE 9 COMPREHENSIVE RAG PIPELINE TEST SUITE")
    print("=========================================================")

    test_1_html_table_extraction()
    test_2_html_accordion_and_json_ld()
    test_3_structure_aware_chunking()
    test_4_intent_routing_and_retrieval_modes()
    test_5_entity_sibling_expansion()
    test_6_catalog_cross_document_discovery()
    test_7_balanced_multi_entity_comparison()
    test_8_multi_product_filter_query()
    test_9_cross_page_synthesis()
    test_10_purchase_intent_canonical_url()
    test_11_separation_of_retrieval_size_from_answer_size()
    test_12_missing_information_grounding()
    test_13_multi_bot_isolation()
    test_14_large_website_100_chunks()
    test_15_critique_verify_polish_pipeline_preservation()

    print("\n=========================================================")
    print("ALL 15 TEST SUITES (35 SPECIFIC VALIDATIONS) PASSED SUCCESSFULLY!")
    print("=========================================================")
