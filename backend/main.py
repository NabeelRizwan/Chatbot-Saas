import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError
from utils.rate_limiter import RateLimitMiddleware

from database.connection import SessionLocal
from routes import admin_routes, analytics_routes, auth_routes, billing_routes, bot_routes, chat_routes, conversation_routes, customer_routes, ingest_routes, knowledge_routes, organization_routes, public_routes
from services.billing_service import ensure_default_plans
from services.security_config_service import validate_production_security
from services.health_service import liveness_status, readiness_status


def _cors_origins() -> list[str]:
    """Return the configured browser origins without changing widget defaults."""
    raw_origins = os.getenv("CORS_ALLOWED_ORIGINS", "*")
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()] or ["*"]


def _validate_production_settings() -> None:
    validate_production_security(os.environ)


_validate_production_settings()

# Schema changes are owned by Alembic and run before the API process starts.
# Application import must never mutate schema or continue after a failed migration.
_db = SessionLocal()
try:
    ensure_default_plans(_db)
finally:
    _db.close()

app = FastAPI(
    title="Chatbot SaaS API",
    description="Multi-tenant, multi-provider RAG backend with PostgreSQL/pgvector.",
    version="2.0.0",
)


@app.exception_handler(OperationalError)
@app.exception_handler(DBAPIError)
async def db_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=503,
        content={"detail": "Database connection failed. Please ensure your Supabase/PostgreSQL project is unpaused and DATABASE_URL in backend/.env is valid."},
    )

# Widgets are designed to run on a customer's website. Keep the default wildcard
# when that is required, or supply a comma-separated CORS_ALLOWED_ORIGINS list.
cors_origins = _cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[] if "*" in cors_origins else cors_origins,
    allow_origin_regex=r"https?://.*" if "*" in cors_origins else None,
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
# The legacy synchronous ingestion API bypasses durable jobs and is retained
# only for local backwards compatibility. Production uses /knowledge so API
# and worker replicas remain independent and retry-safe.
if os.getenv("APP_ENV", "development").lower() not in {"production", "prod"}:
    app.include_router(ingest_routes.router, prefix="/ingest", tags=["Legacy Development Ingestion"])
app.include_router(knowledge_routes.router, prefix="/knowledge", tags=["Knowledge"])
app.include_router(chat_routes.router, prefix="/chat", tags=["Chat"])
app.include_router(public_routes.router, prefix="/public", tags=["Public Widget"])
app.include_router(analytics_routes.router, prefix="/analytics", tags=["Analytics"])
app.include_router(conversation_routes.router, tags=["Conversations"])


@app.get("/health")
def health_check():
    return liveness_status()


@app.get("/health/live")
def health_liveness():
    return liveness_status()


@app.get("/health/ready")
def health_readiness():
    ready, payload = readiness_status()
    if not ready:
        return JSONResponse(status_code=503, content=payload)
    return payload


@app.get("/")
def root():
    return {"status": "API running", "phase": "4c-knowledge-rag"}
