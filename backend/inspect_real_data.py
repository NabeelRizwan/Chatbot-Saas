import sys
from pathlib import Path
from bs4 import BeautifulSoup

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from database.connection import SessionLocal
from database.models import Bot, Document, Chunk

db = SessionLocal()
b = db.query(Bot).filter(Bot.name.like('IKEA_Live_Bot%')).order_by(Bot.id.desc()).first()
if not b:
    print("No IKEA bot found in DB.")
    sys.exit(0)

docs = db.query(Document).filter(Document.bot_id == b.id).all()
chunks = db.query(Chunk).filter(Chunk.bot_id == b.id).all()

print(f"Bot ID: {b.id} ({b.name})")
print(f"Total Documents: {len(docs)}")
print(f"Total Chunks in DB: {len(chunks)}")

canonicals = []
ctas = []
json_lds = []

for d in docs:
    meta = d.metadata_json or {}
    if meta.get("canonical_url"):
        canonicals.append((d.source_url, meta.get("canonical_url")))
    if meta.get("json_ld"):
        json_lds.append((d.source_url, meta.get("json_ld")))
    for c in meta.get("cta_links", []):
        ctas.append((d.source_url, c))

print(f"\nReal Canonical URLs Extracted: {len(canonicals)}")
for src, can in canonicals[:5]:
    print(f"  Source: {src}\n  -> Canonical: {can}")

print(f"\nReal JSON-LD Blocks Extracted: {len(json_lds)}")
for src, jld in json_lds[:3]:
    print(f"  Source: {src}\n  -> Items: {len(jld)}")

print(f"\nReal CTAs Extracted: {len(ctas)}")
for src, c in ctas[:8]:
    print(f"  Source: {src}\n  -> Text: '{c.get('text')}' | URL: {c.get('url')} | Type: {c.get('type')}")

db.close()
