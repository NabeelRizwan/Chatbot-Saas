from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from utils.rate_limiter import RateLimitMiddleware

from database.connection import Base, SessionLocal, create_vector_indexes, engine, init_db
from routes import admin_routes, analytics_routes, auth_routes, billing_routes, bot_routes, chat_routes, conversation_routes, customer_routes, ingest_routes, knowledge_routes, organization_routes, public_routes
from services.billing_service import ensure_default_plans
# Import models before create_all so SQLAlchemy registers every table.
from database import models  # noqa: F401

init_db()
Base.metadata.create_all(bind=engine)
_db = SessionLocal()
try:
    ensure_default_plans(_db)
finally:
    _db.close()
create_vector_indexes()

app = FastAPI(
    title="Chatbot SaaS API",
    description="Multi-tenant RAG backend powered by Gemini and pgvector.",
    version="2.0.0",
)

# CORS is intentionally open for early widget development. Lock this to your
# production domains before launch.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)

app.include_router(admin_routes.router, prefix="/admin", tags=["Admin"])
app.include_router(customer_routes.router, prefix="/customer", tags=["Customers"])
app.include_router(auth_routes.router, prefix="/auth", tags=["Authentication"])
app.include_router(organization_routes.router, prefix="/organizations", tags=["Organizations"])
app.include_router(billing_routes.router, prefix="/billing", tags=["Billing"])
app.include_router(bot_routes.collection_router, tags=["Bots"])
app.include_router(bot_routes.router, prefix="/bot", tags=["Bots"])
app.include_router(ingest_routes.router, prefix="/ingest", tags=["Ingestion"])
app.include_router(knowledge_routes.router, prefix="/knowledge", tags=["Knowledge"])
app.include_router(chat_routes.router, prefix="/chat", tags=["Chat"])
app.include_router(public_routes.router, prefix="/public", tags=["Public Widget"])
app.include_router(analytics_routes.router, prefix="/analytics", tags=["Analytics"])
app.include_router(conversation_routes.router, tags=["Conversations"])


@app.get("/widget.js", include_in_schema=False)
def widget_script():
    widget_path = Path(__file__).resolve().parents[1] / "widget" / "script.js"
    return FileResponse(widget_path, media_type="application/javascript")


@app.get("/health")
def health_check():
    return {"status": "healthy", "database": "connected"}


@app.get("/")
def root():
    return {"status": "API running", "phase": "4c-knowledge-rag"}
