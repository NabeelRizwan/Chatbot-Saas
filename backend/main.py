import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from utils.rate_limiter import RateLimitMiddleware

from database.connection import Base, SessionLocal, create_vector_indexes, engine, init_db
from routes import admin_routes, analytics_routes, auth_routes, billing_routes, bot_routes, chat_routes, conversation_routes, customer_routes, ingest_routes, knowledge_routes, organization_routes, public_routes
from services.billing_service import ensure_default_plans
# Import models before create_all so SQLAlchemy registers every table.
from database import models  # noqa: F401


def _cors_origins() -> list[str]:
    """Return the configured browser origins without changing widget defaults."""
    raw_origins = os.getenv("CORS_ALLOWED_ORIGINS", "*")
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()] or ["*"]


def _validate_production_settings() -> None:
    if os.getenv("APP_ENV", "development").lower() not in {"production", "prod"}:
        return
    jwt_secret = os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY")
    if not jwt_secret or jwt_secret == "dev-change-me-before-production":
        raise RuntimeError("JWT_SECRET must be set to a strong value when APP_ENV=production.")


_validate_production_settings()

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

# Widgets are designed to run on a customer's website. Keep the default wildcard
# when that is required, or supply a comma-separated CORS_ALLOWED_ORIGINS list.
cors_origins = _cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials="*" not in cors_origins,
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


@app.get("/health")
def health_check():
    return {"status": "healthy", "database": "connected"}


@app.get("/")
def root():
    return {"status": "API running", "phase": "4c-knowledge-rag"}
