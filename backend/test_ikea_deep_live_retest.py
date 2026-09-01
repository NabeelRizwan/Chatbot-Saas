import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Ensure UTF-8 output encoding on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from database.connection import SessionLocal
from database.models import Bot, Chunk, Customer, Document, Organization, Website, WebsiteCrawl
from services.chunking_service import CHUNK_OVERLAP, CHUNK_SIZE, chunk_text_with_metadata, count_tokens
from services.conversational_engine import compress_and_rerank_chunks, global_semantic_cache
from services.coverage_manifest_service import (
    build_website_coverage_manifest,
    infer_document_relationships,
)
from services.crawl4ai_service import crawl_single_page
from services.embedding_service import generate_embeddings_batch
from services.firecrawl_service import Page
from services.rag_service import answer_question, clear_retrieval_cache

import fakeredis
import fakeredis.aioredis
from utils.redis_client import set_redis_override


def main():
    print("=" * 80)
    print("PHASE 10: REAL-WORLD IKEA DEEP WEBSITE INGESTION & CHATBOT COVERAGE RETEST")
    print("=" * 80)

    fake_redis = fakeredis.FakeRedis()
    fake_async_redis = fakeredis.aioredis.FakeRedis()
    set_redis_override(fake_redis, fake_async_redis)

    seed_url = "https://www.ikea.com/in/en/cat/storage-organisation-st001/"
    child_urls = [
        ("https://www.ikea.com/in/en/cat/storage-organisation-st001/", "Storage & Organisation Hub"),
        ("https://www.ikea.com/in/en/cat/bookcases-shelving-units-st002/", "Bookcases & Shelving Units"),
        ("https://www.ikea.com/in/en/cat/boxes-baskets-10550/", "Boxes & Baskets"),
        ("https://www.ikea.com/in/en/cat/shoe-cabinets-shoe-racks-for-hallway-10456/", "Shoe Cabinets & Shoe Racks"),
        ("https://www.ikea.com/in/en/cat/food-storage-organising-15937/", "Food Storage & Organising"),
    ]

    # Step 1: Live Deep Crawling of Seed Hub + Child Subcategory Pages
    print(f"\n[1/5] Deep Crawling {len(child_urls)} Multi-Level Pages from Seed: {seed_url}...")
    t0_crawl = time.perf_counter()
    crawled_pages: List[Page] = []

    for url, fallback_title in child_urls:
        print(f"  -> Crawling: {url}")
        p = crawl_single_page(url)
        if p.status == "success" and p.markdown:
            title = p.title or fallback_title
            crawled_pages.append(
                Page(
                    url=url,
                    title=title,
                    markdown=p.markdown,
                    metadata={"source_url": url, "page_title": title, "links": p.links},
                    links=p.links,
                )
            )
            print(f"     [OK] '{title}' ({len(p.markdown):,} chars, {len(p.links)} links)")
        else:
            print(f"     [WARN] Fallback crawl for {url}")

    crawl_duration = time.perf_counter() - t0_crawl
    print(f"\nCompleted Deep Ingestion Crawl in {crawl_duration:.2f}s ({len(crawled_pages)} pages).")

    # Step 2: Database Storage & Document Relationship Linking
    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.name == "IKEA Retail Org").first()
        if not org:
            org = Organization(name="IKEA Retail Org", slug="ikea-retail-org-p10")
            db.add(org)
            db.commit()
            db.refresh(org)

        customer = db.query(Customer).filter(Customer.name == "IKEA India").first()
        if not customer:
            customer = Customer(name="IKEA India", api_key="ikea_prod_key_live_2026")
            db.add(customer)
            db.commit()
            db.refresh(customer)

        bot = db.query(Bot).filter(Bot.name == "IKEA Deep Storage Assistant").first()
        if not bot:
            bot = Bot(
                name="IKEA Deep Storage Assistant",
                customer_id=customer.id,
                organization_id=org.id,
                system_prompt="You are the official IKEA India Storage & Organisation expert assistant. Answer customer questions accurately using official IKEA product and category information from our website. Keep answers direct and helpful.",
                model_name="gemini-2.5-flash",
            )
            db.add(bot)
            db.commit()
            db.refresh(bot)

        print(f"\n[2/5] Initialized Bot ID {bot.id}: '{bot.name}' (Org ID {org.id})")

        # Clean existing test data for this bot
        db.query(Chunk).filter(Chunk.bot_id == bot.id).delete()
        db.query(Document).filter(Document.bot_id == bot.id).delete()
        db.commit()

        # Build Document Relationships & Hierarchy
        page_dicts = [
            {"url": p.url, "title": p.title, "raw_text": p.markdown, "metadata": p.metadata}
            for p in crawled_pages
        ]
        doc_nodes = infer_document_relationships(page_dicts, root_url=seed_url)
        node_map = {n.url: n for n in doc_nodes}

        # Step 3: Ingest Documents & Chunks with Contextual Hierarchy
        print(f"\n[3/5] Ingesting {len(crawled_pages)} Documents & Generating Batch Embeddings...")
        total_chunks_created = 0

        for idx, page in enumerate(crawled_pages):
            node_rel = node_map.get(page.url)
            doc_meta = {
                "source_url": page.url,
                "page_title": page.title,
                "parent_url": node_rel.parent_url if node_rel else None,
                "category_path": node_rel.category_path if node_rel else [],
                "entity_type": node_rel.entity_type if node_rel else "category",
                "cta_links": [{"text": f"Shop {page.title}", "url": page.url}],
            }

            doc = Document(
                bot_id=bot.id,
                organization_id=org.id,
                source_type="website",
                source_url=page.url,
                filename=f"ikea-{idx}-{Path(page.url).name or 'hub'}",
                title=page.title,
                raw_text=page.markdown,
                status="ready",
                processing_status="completed",
                crawl_depth=node_rel.depth if node_rel else 0,
                metadata_json=doc_meta,
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)

            chunks_data = chunk_text_with_metadata(
                page.markdown,
                chunk_size=CHUNK_SIZE,
                overlap=CHUNK_OVERLAP,
                page_title=page.title,
                source_url=page.url,
                metadata=doc_meta,
            )
            chunk_texts = [c.content for c in chunks_data]
            embeddings = generate_embeddings_batch(chunk_texts, org_id=org.id)

            for c_idx, c in enumerate(chunks_data):
                db.add(
                    Chunk(
                        bot_id=bot.id,
                        organization_id=org.id,
                        document_id=doc.id,
                        chunk_index=c.index,
                        content=c.content,
                        token_count=c.token_count,
                        embedding=embeddings[c_idx],
                        status="ready",
                        metadata_json={
                            "source_url": page.url,
                            "page_title": page.title,
                            "parent_url": doc_meta["parent_url"],
                            "category_path": doc_meta["category_path"],
                            "entity_type": doc_meta["entity_type"],
                            "heading": c.heading,
                            "section": c.section,
                            "cta_links": doc_meta["cta_links"],
                        },
                    )
                )
                total_chunks_created += 1
            db.commit()

        print(f"Created {total_chunks_created} pgvector embedded chunks across {len(crawled_pages)} documents.")

        # Step 4: Generate Website Coverage Manifest
        print("\n[4/5] Generating Website Knowledge Coverage Manifest...")
        manifest = build_website_coverage_manifest(page_dicts, root_url=seed_url)
        print("\n" + "=" * 80)
        print("IKEA STORAGE & ORGANISATION COVERAGE TREE MANIFEST")
        print("=" * 80)
        print(manifest["ascii_tree"])
        print("=" * 80)

        # Step 5: Execute All 10 Real Customer Queries
        print("\n[5/5] Executing Chatbot Retest Across All 10 Realistic Customer Questions...")
        print("=" * 80)

        test_questions = [
            ("Category Overview", "What storage and organisation solutions do you offer?"),
            ("Wardrobes & Modular Storage", "What wardrobe and modular clothes storage options are available?"),
            ("Bookcases & Shelving", "Do you have bookcases, shelving units, and storage systems like BILLY or KALLAX?"),
            ("Boxes & Baskets (Phase 10 Target)", "What small storage organisers, boxes, and baskets do you sell?"),
            ("Shoe Storage (Phase 10 Target)", "What shoe racks, shoe cabinets, or hallway storage do you have?"),
            ("Kitchen Organisers (Phase 10 Target)", "Where can I find kitchen & pantry food storage organisers?"),
            ("Pricing & Specifications", "How much does the BRUSALI shoe cabinet or KULLEN chest cost?"),
            ("Purchase & Action Intent", "Where can I browse and buy your storage and organisation products online?"),
            ("Product Specifications", "What are the dimensions and specs of the BRIMNES wardrobe with 3 doors?"),
            ("Missing Information / Grounding", "Do you sell live goldfish in aquarium tanks?"),
        ]

        chat_results = []
        clear_retrieval_cache()
        global_semantic_cache.clear()

        for idx, (category_label, query) in enumerate(test_questions, start=1):
            print(f"\n--- Customer Query #{idx} [{category_label}] ---")
            print(f"User: \"{query}\"")

            t0_qa = time.perf_counter()
            reply, sources, retrieved_chunks = answer_question(
                db=db,
                bot=bot,
                question=query,
                history=[],
            )
            qa_duration_ms = (time.perf_counter() - t0_qa) * 1000

            print(f"\nChatbot Response ({qa_duration_ms:.2f}ms):")
            print(f"{reply.strip()}")
            print(f"\nSources Referenced: {sources}")
            print(f"Retrieved Chunks Used: {len(retrieved_chunks)}")
            print("-" * 80)

            chat_results.append({
                "index": idx,
                "category": category_label,
                "query": query,
                "reply": reply.strip(),
                "sources": sources,
                "chunks_retrieved": len(retrieved_chunks),
                "latency_ms": qa_duration_ms,
            })
            time.sleep(1.0)  # Gentle rate limit pause between queries

        # Write results to json file for reference
        results_file = BACKEND_DIR / "ikea_deep_live_retest_results.json"
        with open(results_file, "w", encoding="utf-8") as f:
            json.dump({
                "seed_url": seed_url,
                "crawled_pages": len(crawled_pages),
                "total_chunks": total_chunks_created,
                "manifest_tree": manifest["ascii_tree"],
                "chat_results": chat_results,
            }, f, indent=2, ensure_ascii=False)
        print(f"\n[SUCCESS] Saved Phase 10 validation logs to: {results_file}")

    finally:
        set_redis_override(None, None)
        db.close()


if __name__ == "__main__":
    main()
