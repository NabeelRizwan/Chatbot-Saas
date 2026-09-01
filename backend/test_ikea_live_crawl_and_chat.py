import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure UTF-8 output encoding on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from database.connection import SessionLocal
from database.models import Bot, Chunk, Customer, Document, Website, WebsiteCrawl
from services.chunking_service import CHUNK_OVERLAP, CHUNK_SIZE, chunk_text_with_metadata, count_tokens
from services.crawl4ai_service import crawl_single_page
from services.embedding_service import generate_embeddings_batch
from services.rag_service import answer_question, clear_retrieval_cache
from services.conversational_engine import global_semantic_cache

import fakeredis
import fakeredis.aioredis
from utils.redis_client import set_redis_override


def main():
    print("=" * 80)
    print("LIVE IKEA STORAGE & ORGANISATION CRAWL & FULL CHATBOT RAG EXECUTION")
    print("=" * 80)

    fake_redis = fakeredis.FakeRedis()
    fake_async_redis = fakeredis.aioredis.FakeRedis()
    set_redis_override(fake_redis, fake_async_redis)

    target_url = "https://www.ikea.com/in/en/cat/storage-organisation-st001/?utm_source=chatgpt.com"
    clean_canonical_url = "https://www.ikea.com/in/en/cat/storage-organisation-st001/"

    # Step 1: Live Crawl with Playwright DOM extraction
    print(f"\n[1/4] Crawling Target URL: {target_url}...")
    t0_crawl = time.perf_counter()
    page = crawl_single_page(target_url)
    crawl_duration = time.perf_counter() - t0_crawl

    print(f"Crawl Completed in: {crawl_duration:.2f}s")
    print(f"Status: {page.status} (HTTP {page.status_code})")
    print(f"Page Title: {page.title}")
    print(f"Extracted Markdown Length: {len(page.markdown):,} characters")
    print(f"Extracted Word Count: {len(page.markdown.split()):,} words")
    print(f"Discovered Links: {len(page.links)} links")

    # Step 2: Database Storage & Vector Embedding Generation
    db = SessionLocal()
    try:
        # Create Dedicated IKEA Customer & Bot
        customer = db.query(Customer).filter(Customer.name == "IKEA India").first()
        if not customer:
            customer = Customer(name="IKEA India", api_key="ikea_prod_key_live_2026")
            db.add(customer)
            db.commit()
            db.refresh(customer)

        bot = db.query(Bot).filter(Bot.name == "IKEA Storage Assistant").first()
        if not bot:
            bot = Bot(
                name="IKEA Storage Assistant",
                customer_id=customer.id,
                organization_id=customer.id,
                system_prompt="You are the official IKEA India Storage & Organisation expert assistant. Answer customer questions accurately using only official IKEA product and category information from the website. Keep answers direct and helpful.",
                model_name="gemini-2.5-flash",
            )
            db.add(bot)
            db.commit()
            db.refresh(bot)

        print(f"\n[2/4] Initialized Bot ID {bot.id}: '{bot.name}'")

        # Clean existing test data for this bot
        db.query(Chunk).filter(Chunk.bot_id == bot.id).delete()
        db.query(Document).filter(Document.bot_id == bot.id).delete()
        db.commit()

        # Ingest Document
        doc = Document(
            bot_id=bot.id,
            organization_id=bot.organization_id,
            source_type="website",
            source_url=clean_canonical_url,
            filename="ikea-storage-organisation",
            title=page.title,
            raw_text=page.markdown,
            status="ready",
            processing_status="completed",
            metadata_json={
                "source_url": clean_canonical_url,
                "page_title": page.title,
                "original_url": target_url,
                "cta_links": [{"text": "Shop Storage & Organisation", "url": clean_canonical_url}],
            },
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        # Chunk Document
        print("\n[3/4] Performing Structure-Aware Chunking & Batch Embeddings...")
        t0_chunk = time.perf_counter()
        chunks_data = chunk_text_with_metadata(
            page.markdown,
            chunk_size=CHUNK_SIZE,
            overlap=CHUNK_OVERLAP,
            page_title=page.title,
            source_url=clean_canonical_url,
            metadata={"source_url": clean_canonical_url, "page_title": page.title},
        )
        chunk_texts = [c.content for c in chunks_data]
        embeddings = generate_embeddings_batch(chunk_texts, org_id=bot.organization_id)

        for idx, c in enumerate(chunks_data):
            chunk_row = Chunk(
                bot_id=bot.id,
                organization_id=bot.organization_id,
                document_id=doc.id,
                chunk_index=c.index,
                content=c.content,
                token_count=c.token_count,
                embedding=embeddings[idx],
                status="ready",
                metadata_json={
                    "source_url": clean_canonical_url,
                    "page_title": page.title,
                    "heading": c.heading,
                    "section": c.section,
                },
            )
            db.add(chunk_row)
        db.commit()
        chunk_duration = time.perf_counter() - t0_chunk
        print(f"Created {len(chunks_data)} pgvector embedded chunks in {chunk_duration:.2f}s.")

        # Step 3: Run Full Chatbot Answering Pipeline Across 8 Realistic Customer Questions
        print("\n[4/4] Executing Full Chatbot Pipeline (Generate -> Critique -> Polish) on Live Ingested IKEA Knowledge...")
        print("=" * 80)

        test_questions = [
            ("Category Overview", "What storage and organisation solutions do you offer?"),
            ("Wardrobes & Clothes Storage", "What wardrobe and clothes storage options are available?"),
            ("Bookcases & Shelving", "Do you have bookcases, shelving units, and storage systems?"),
            ("Boxes & Small Organisers", "What small storage organisers, boxes, and baskets do you sell?"),
            ("Shoe Storage & Hooks", "What shoe racks, hat and coat stands, or wall hooks do you have?"),
            ("Brevity Factual Test", "Where can I find kitchen & pantry food storage organisers?"),
            ("Purchase & Action Intent", "Where can I browse and buy your storage and organisation products online?"),
            ("Missing Information Test", "Do you sell live goldfish in aquarium tanks?"),
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

        # Step 4: Summary Output
        print("\n" + "=" * 80)
        print("IKEA LIVE CRAWL & CHATBOT VALIDATION SUMMARY")
        print("=" * 80)
        print(f"Source URL:                 {target_url}")
        print(f"Page Title:                 {page.title}")
        print(f"Extracted Characters:       {len(page.markdown):,}")
        print(f"Extracted Words:            {len(page.markdown.split()):,}")
        print(f"Indexed Chunks:             {len(chunks_data)}")
        print(f"Chatbot Queries Executed:   {len(test_questions)}")
        avg_latency = sum(r["latency_ms"] for r in chat_results) / len(chat_results)
        print(f"Average Chatbot Latency:    {avg_latency:.2f}ms")
        print("=" * 80)

        # Write results to json file for reference
        results_file = BACKEND_DIR / "ikea_live_chat_results.json"
        with open(results_file, "w", encoding="utf-8") as f:
            json.dump({
                "target_url": target_url,
                "title": page.title,
                "markdown_length": len(page.markdown),
                "word_count": len(page.markdown.split()),
                "total_chunks": len(chunks_data),
                "chat_results": chat_results,
            }, f, indent=2, ensure_ascii=False)
        print(f"\nSaved complete benchmark logs to: {results_file}")

    finally:
        set_redis_override(None, None)
        db.close()


if __name__ == "__main__":
    main()
