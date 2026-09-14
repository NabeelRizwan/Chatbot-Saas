"""One bulk, synthetic-only catalog. Golden expectations frozen before SQL runs."""
from types import SimpleNamespace
from time import perf_counter
from sqlalchemy import insert, text

# Explicit, realistic metadata aliases, not entire question strings or fuzzy merges.
NATURAL = (
    (3001, "Web Development Service", "service", ["Web Dev Service", "Website Development"]),
    (3002, "AI Consulting", "service", ["Artificial Intelligence Consulting"]),
    (3003, "Customer Support Automation", "service", ["Support Automation"]),
    (3004, "Mobile App and Backend Development", "service", ["Full Stack App Development"]),
    (3005, "International Student Application Form", "form", ["International Application Form", "Application Form"]),
    (3006, "Data Science Course Brochure", "pdf", ["Data Science Brochure"]),
    (3007, "Academic Ebook", "ebook", ["Academic Ebook Section"]),
    (3008, "Professional Program", "program", ["Pro", "Advanced Program"]),
    (3009, "Basic Program", "program", ["Introductory Program"]),
    (3010, "Starter Plan", "plan", ["Starter", "Basic Plan"]),
    (3011, "Professional Plan", "plan", ["Professional", "Pro"]),
    (3012, "Enterprise Plan", "plan", ["Enterprise"]),
    (3013, "Hyderabad Office", "location", ["Hyderabad Branch"]),
    (3014, "Pune Branch", "location", ["Pune Office"]),
    (3015, "Support Department", "department", ["Customer Support Department"]),
    (3016, "Refund Policy", "policy", ["Returns Policy"]),
    (3017, "Terms PDF", "pdf", ["Terms and Conditions"]),
    (3018, "Warranty Page", "policy", ["Warranty Information"]),
    (3019, "Admissions Form", "form", ["Admission Form"]),
    (3020, "Scholarship Form", "form", ["Scholarship Application"]),
    (3021, "Data Science Course", "course", ["Data Science Training"]),
    (3022, "Evening Design Course", "course", ["Design Training"]),
)

# First 30 include positive single/multi/category/navigation cases for the
# application handoff. Negative/ambiguous expectations are explicit, never
# converted from a failed positive after observing runtime output.
GOLDEN = (
    ("Do you guys build websites or mostly do AI consulting?", (3001,3002), "positive"),
    ("I'm looking for someone to automate customer support. Is that something you offer?", (3003,), "positive"),
    ("Which service would I need if I want both an app and backend?", (3004,), "positive"),
    ("Where can I find the application form for international students?", (3005,), "positive"),
    ("Can you send me the brochure for the data science course?", (3006,), "positive"),
    ("Where's the academic ebook section?", (3007,), "positive"),
    ("Do you have a professional version of this program or only the basic one?", (3008,3009), "positive"),
    ("What's the difference between Starter and Professional?", (3010,3011), "positive"),
    ("I think the plan was called Pro — can you show me the right one?", (), "ambiguous"),
    ("Do you have something between the basic plan and enterprise?", (3011,), "positive"),
    ("How do I contact your Hyderabad office?", (3013,), "positive"),
    ("Does your Pune branch offer this service too?", (3014,), "positive"),
    ("Where can I find the support department?", (3015,), "positive"),
    ("Where's your refund policy?", (3016,), "positive"),
    ("Can you send me the terms PDF?", (3017,), "positive"),
    ("I saw a warranty page earlier but can't find it now.", (3018,), "positive"),
    ("admisson form", (3019,), "positive"),
    ("profesional plan", (3011,), "positive"),
    ("acadmic ebook", (3007,), "positive"),
    ("web dev service", (3001,), "positive"),
    ("Should I look at the Starter plan or the Professional one?", (3010,3011), "positive"),
    ("Do you offer AI consulting or web development?", (3001,3002), "positive"),
    ("Can you send me either the admissions form or scholarship form?", (3019,3020), "positive"),
    ("Show me Pro.", (), "ambiguous"),
    ("What services do you offer?", (3001,3002,3003,3004), "category"),
    ("What courses are available?", (3021,3022), "category"),
    ("What plans do you have?", (3010,3011,3012), "category"),
    ("Where can I find the application form?", (3005,), "positive"),
    ("Where can I find the Data Science Course Brochure?", (3006,), "positive"),
    ("Tell me about Customer Support Automation.", (3003,), "positive"),
    ("How do I contact the Pune Office?", (3014,), "positive"),
    ("Show me your Refund Policy.", (3016,), "positive"),
    ("Where is the Warranty Page?", (3018,), "positive"),
    ("Send me the Scholarship Form.", (3020,), "positive"),
    ("Tell me about the Evening Design Course.", (3022,), "positive"),
    ("Compare Starter Plan and Enterprise Plan.", (3010,3012), "positive"),
    ("Compare Basic Program and Professional Program.", (3008,3009), "positive"),
    ("Where can I download the International Student Application Form?", (3005,), "positive"),
    ("Tell me about Web Development Service.", (3001,), "positive"),
    ("Where can I find the Academic Ebook?", (3007,), "positive"),
    ("Show me your locations.", (3013,3014), "category"),
    ("What programs are available?", (3008,3009), "category"),
    ("Tell me about Professional Plan.", (3011,), "positive"),
    ("Where is the Support Department?", (3015,), "positive"),
    ("Show me the Terms PDF.", (3017,), "positive"),
    ("Tell me about Quantum Teleportation Service.", (), "unresolved"),
    ("Where can I find the Lunar Immigration Permit?", (), "unresolved"),
    ("Show me HR.", (), "unresolved"),
    ("Tell me about Plan 90909.", (), "unresolved"),
    ("Show me AI.", (), "unresolved"),
)


def vector(number=0):
    values = [0.] * 768
    values[0], values[1 + number % 31] = 1., .25
    return values


def documents():
    from test_resource_discovery_benchmark import SEEDS
    rows = []
    def add(number, name, *, org=1, bot=1, aliases=(), kind="document", breadcrumb=(), url=None):
        rows.append(dict(id=number, organization_id=org, bot_id=bot, title=name, filename="source.txt",
            source_type="txt", canonical_url=url or f"https://synthetic.test/{number}", status="ready",
            processing_status="completed", version=1, crawl_id=None,
            metadata_json={"aliases": list(aliases), "resource_type": kind, "breadcrumb": list(breadcrumb)}))
    # Identical membership/identity metadata to populate() in the frozen benchmark.
    for i, (stem, kind, _) in enumerate(SEEDS, 1):
        a,b = stem.split()
        add(i*10, f"{stem} {kind.replace('_',' ')}", kind=kind,
            aliases=[stem+" Desk", "Pro", "Shared Desk", f"Café {a} 東京", f"{a} Unit {2020+i}"],
            breadcrumb=[f"Directory {a} {b}"], url=f"https://synthetic.test/{a}-{b}-portal")
        add(i*10+1, f"{a} Common Extended", kind=kind, aliases=[f"{a} Common"])
        add(i*10+2, f"{a} Common Compact", kind="other", aliases=[f"{a} Common"])
        add(10000+i, f"{stem} {kind.replace('_',' ')}", kind=kind, bot=2)
        add(20000+i, f"{stem} {kind.replace('_',' ')}", kind=kind, org=2, bot=3)
    add(999, "Neutral Atlas Reference", kind="custom")
    for number,name,kind,aliases in NATURAL:
        add(number, name, kind=kind, aliases=aliases, org=3, bot=4, breadcrumb=["Visitor Resources",kind])
    remaining = 6000-len(rows)
    for i in range(remaining):
        org = 4+i % 27  # Natural golden organization is not polluted by scale boilerplate.
        add(100000+i, f"Atlas Sector {i} Reference", org=org, bot=org+1, kind="custom",
            aliases=[f"Atlas Registry {i}", f"Sector Archive {i}", f"Reference Code {i}"],
            breadcrumb=[f"Registry Region {org}"])
    return rows


def bulk_seed(conn):
    from database.models import Customer, Organization, Bot, Document, Chunk
    from database.resource_models import KnowledgeResource as Resource, KnowledgeResourceTerm as Term, KnowledgeResourceDocument as Link
    from services.resource_catalog import projection
    started=perf_counter()
    conn.execute(insert(Customer.__table__), [{"id":1,"name":"Synthetic only","api_key":"fixture-not-a-secret"}])
    conn.execute(insert(Organization.__table__), [{"id":i,"name":f"Synthetic {i}","slug":f"synthetic-{i}"} for i in range(1,31)])
    bots=[{"id":1,"organization_id":1},{"id":2,"organization_id":1},{"id":3,"organization_id":2}]
    bots += [{"id":i+1,"organization_id":i} for i in range(3,31)]
    conn.execute(insert(Bot.__table__), [{**b,"customer_id":1,"name":f"Synthetic bot {b['id']}","capabilities":{}} for b in bots])
    docs=documents()
    resources, terms, links, chunks=[],[],[],[]
    for d in docs:
        key,attrs,wanted=projection(SimpleNamespace(**d, source_url=None))
        common={"organization_id":d["organization_id"],"bot_id":d["bot_id"]}
        resources.append({**common,"id":d["id"],"source_key":key,**attrs,"status":"ready","version":1,
                          "metadata_json":{"primary_document_id":d["id"]},"summary":"90-day refund guarantee" if d["id"]==3016 else None})
        links.append({**common,"resource_id":d["id"],"document_id":d["id"],"document_version":1})
        for display,normalized,kind,source in wanted:
            terms.append({**common,"resource_id":d["id"],"term_text":display,"normalized_term":normalized,
                          "term_kind":kind,"term_source":source,"source_document_id":d["id"],"source_version":1})
        content=f"{d['title']}. Synthetic source reference {d['id']}. Contact hours are Monday to Friday, 09:00 to 17:00. Directions: complete the listed form and contact the team. No refund duration is stated."
        chunks.append({**common,"id":d["id"],"document_id":d["id"],"chunk_index":0,"content":content,
                       "status":"ready","embedding":vector(d["id"]),"embedding_provider":"gemini",
                       "embedding_model":"gemini-embedding-001","embedding_version":1})
    for table,rows,batch in ((Document.__table__,docs,1000),(Chunk.__table__,chunks,128),
                             (Resource.__table__,resources,500),(Term.__table__,terms,1000),(Link.__table__,links,1000)):
        for offset in range(0,len(rows),batch):
            conn.execute(insert(table), rows[offset:offset+batch])
    for table in ("documents","chunks","knowledge_resources"):
        conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}','id'),(SELECT max(id) FROM {table}))"))
    conn.commit()
    return {"organizations":30,"bots":31,"documents":len(docs),"resources":len(resources),
            "terms":len(terms),"chunks":len(chunks),"bulk_seed_seconds":perf_counter()-started,
            "method":"SQLAlchemy Core bounded executemany/insertmanyvalues; one dataset, no per-row commits"}
