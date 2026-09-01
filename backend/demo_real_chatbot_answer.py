import json
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure backend root is on sys.path
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from database.connection import SessionLocal
from database.models import Bot, Chunk, Customer, Document
from services.crawl4ai_service import crawl_website
from services.document_processing_service import process_document
from services.rag_service import answer_question


def run_chatbot_demo():
    print("=" * 80)
    print("DEMO: REAL CRAWLED IKEA DATA EXTRACTION & PRODUCTION CHATBOT EXECUTION")
    print("=" * 80)

    db = SessionLocal()
    try:
        customer = db.query(Customer).first()
        if not customer:
            customer = Customer(
                name="DemoCustomer",
                api_key=f"demo_key_{int(datetime.utcnow().timestamp())}",
            )
            db.add(customer)
            db.commit()
            db.refresh(customer)

        bot = Bot(
            name="IKEA India Assistant",
            customer_id=customer.id,
            system_prompt="You are the official helpful customer assistant for IKEA India. Help customers discover furniture, homeware, and room solutions.",
            model_name="gemini-2.5-flash",
        )
        db.add(bot)
        db.commit()
        db.refresh(bot)
        print(f"\n[1/4] Created Dedicated Bot: ID {bot.id} ('{bot.name}')")

        # -------------------------------------------------------------
        # 1. CRAWL REAL IKEA PRODUCT & CATEGORY PAGES
        # -------------------------------------------------------------
        target_urls = [
            "https://www.ikea.com/in/en/cat/products-products/",
            "https://www.ikea.com/in/en/cat/storage-organisation-st001/",
            "https://www.ikea.com/in/en/cat/sofas-armchairs-700640/",
            "https://www.ikea.com/in/en/cat/office-furniture-fu004/",
            "https://www.ikea.com/in/en/cat/beds-mattresses-bm001/",
        ]
        print(f"\n[2/4] Crawling real dynamic catalog pages from IKEA India...")
        crawled_pages = []
        from services.crawl4ai_service import crawl_single_page
        for url in target_urls:
            p = crawl_single_page(url)
            if p.status == "success" and p.markdown:
                crawled_pages.append(p)
                print(f"  -> Crawled: {p.url} | Title: '{p.title}' | Chars: {len(p.markdown)}")

        # -------------------------------------------------------------
        # 2. SHOW EXTRACTED DATA
        # -------------------------------------------------------------
        print("\n" + "=" * 80)
        print("SAMPLE OF EXTRACTED REAL WEBSITE DATA (MARKDOWN)")
        print("=" * 80)
        for idx, p in enumerate(crawled_pages[:3], 1):
            print(f"\n--- Extracted Page #{idx}: {p.title} ---")
            print(f"Source URL: {p.url}")
            print("Extracted Content Preview:\n")
            lines = [l for l in p.markdown.split("\n") if l.strip()][:15]
            print("\n".join(lines))
            print("...\n" + "-" * 60)

        # -------------------------------------------------------------
        # 3. INGEST REAL PAGES INTO DB
        # -------------------------------------------------------------
        print(f"\n[3/4] Ingesting {len(crawled_pages)} real catalog documents into database for Bot {bot.id}...")
        root_doc = Document(
            bot_id=bot.id,
            source_type="website",
            source_url=target_urls[0],
            filename="ikea-products-catalog",
            title=crawled_pages[0].title,
            raw_text="",
            processing_status="pending",
        )
        db.add(root_doc)
        db.commit()
        db.refresh(root_doc)

        from unittest.mock import patch
        with patch("services.document_processing_service.crawl_website", return_value=crawled_pages):
            process_document(db, root_doc.id)

        doc_count = db.query(Document).filter(Document.bot_id == bot.id).count()
        chunk_count = db.query(Chunk).filter(Chunk.bot_id == bot.id).count()
        print(f"  -> Successfully Ingested {doc_count} documents and generated {chunk_count} vector chunks.")

        # -------------------------------------------------------------
        # 4. RUN CHATBOT ON USER QUESTION
        # -------------------------------------------------------------
        question = "What products do you Have?"
        print("\n" + "=" * 80)
        print(f"RUNNING CHATBOT PIPELINE FOR QUESTION: \"{question}\"")
        print("=" * 80)

        reply, sources, retrieved_chunks = answer_question(
            db=db,
            bot=bot,
            question=question,
            top_k=8,
        )

        print("\n" + "#" * 80)
        print("CHATBOT FINAL ANSWER:")
        print("#" * 80 + "\n")
        print(reply)
        print("\n" + "#" * 80)

        print("\nGROUNDED SOURCES USED:")
        for idx, src in enumerate(sources, 1):
            print(f"  [{idx}] {src}")

        print(f"\nTOTAL RETRIEVED CHUNKS: {len(retrieved_chunks)}")
        for idx, chunk in enumerate(retrieved_chunks[:3], 1):
            print(f"  Chunk #{idx}: (Doc ID {chunk.get('document_id', 'N/A')}) -> {chunk.get('content', '')[:120]}...")

    finally:
        # Clean up demo bot
        print("\nCleaning up demo records...")
        db.query(Chunk).filter(Chunk.bot_id == bot.id).delete()
        db.query(Document).filter(Document.bot_id == bot.id).delete()
        db.query(Bot).filter(Bot.id == bot.id).delete()
        db.commit()
        db.close()


if __name__ == "__main__":
    run_chatbot_demo()
