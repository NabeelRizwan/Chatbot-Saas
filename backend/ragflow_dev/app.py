"""Authenticated, bounded development API. No import of the production app/DB."""
from contextlib import asynccontextmanager
import logging
import secrets
from typing import Literal
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from ragflow_derived.contracts import EngineError
from .config import Settings


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Ingest(StrictModel):
    source_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    expected_version: int = Field(ge=0, le=10000, strict=True)
    content: str = Field(min_length=1, max_length=262144)
    kind: Literal["txt", "md", "html", "json", "jsonl", "csv", "xlsx", "docx", "pptx", "epub", "pdf"] = "md"
    encoding: Literal['text', 'base64'] = 'text'
    title: str = Field(default="", max_length=128)
    url: str = Field(default="", max_length=2048)
    child_delimiters: list[str] = Field(default_factory=list, max_length=8)
    auto_keywords: int = Field(default=0, ge=0, le=10, strict=True)
    auto_questions: int = Field(default=0, ge=0, le=10, strict=True)
    generate_toc: bool = False
    metadata: dict = Field(default_factory=dict, max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=32)


class Message(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=16384)


class RetrievalOptions(StrictModel):
    refine_multiturn: bool = False
    cross_languages: list[str] = Field(default_factory=list, max_length=8)
    keyword: bool = False
    toc_enhance: bool = False


class Query(StrictModel):
    query: str = Field(min_length=1, max_length=2048)
    top_k: int = Field(default=12, ge=1, le=48, strict=True)
    rerank: bool = True
    trace: bool = False
    document_ids: list[str] | None = Field(default=None, max_length=30)
    source_versions: dict[str, int] = Field(default_factory=dict, max_length=30)
    organization_id: str | None = None
    bot_id: str | None = None
    generation: str | None = None
    messages: list[Message] = Field(default_factory=list, max_length=63)
    options: RetrievalOptions = Field(default_factory=RetrievalOptions)
    metadata_filter: dict | None = None
    use_tags: bool = False


class Compile(StrictModel):
    kind: Literal['raptor', 'structure', 'graph']
    artifact_sources: list[str] | None = Field(default=None, min_length=1, max_length=30)
    source_versions: dict[str, int] = Field(min_length=1, max_length=30)
    generation: str
    organization_id: str | None = None
    bot_id: str | None = None


class AdvancedQuery(StrictModel):
    mode: Literal['navigation', 'raptor', 'graph', 'agentic']
    query: str = Field(min_length=1, max_length=2048)
    thinking_mode: Literal['low', 'medium', 'high', 'ultra'] = 'medium'
    artifact_kind: Literal['structure', 'raptor', 'graph'] | None = None
    artifact_sources: list[str] | None = Field(default=None, min_length=1, max_length=30)
    document_id: str | None = None
    document_ids: list[str] | None = Field(default=None, max_length=30)
    source_versions: dict[str, int] = Field(default_factory=dict, max_length=30)
    organization_id: str | None = None
    bot_id: str | None = None
    generation: str | None = None
    messages: list[Message] = Field(default_factory=list, max_length=63)
    trace: bool = False


class Delete(StrictModel):
    expected_version: int = Field(ge=1, le=10000, strict=True)


class Fault(StrictModel):
    fault: Literal["storage", "embedding", "reranker"]
    query: str = Field(min_length=1, max_length=2048)


def create_app(settings=None, runtime_factory=None):
    @asynccontextmanager
    async def lifespan(app):
        from .runtime import Runtime
        app.state.settings = settings or Settings.from_env()
        try:
            app.state.runtime = (runtime_factory or Runtime)(app.state.settings)
        except Exception as exc:
            # No raw native/backend exception may leak credentials or source payloads.
            logging.error("RAGFLOW_DEV_STARTUP_FAILED class=%s", type(exc).__name__)
            raise RuntimeError("RAGFLOW_DEV_STARTUP_FAILED") from None
        yield
        app.state.runtime.close()

    app = FastAPI(title="RAGFlow isolated development retrieval", version="1", lifespan=lifespan,
                  docs_url="/docs", redoc_url=None)

    @app.middleware("http")
    async def bounds(request, call_next):
        # Bound streamed bodies too, before JSON parsing. Public health has no body.
        maximum, received = 1_100_000, 0
        receive = request._receive
        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > maximum:
                raise EngineError("INPUT_TOO_LARGE", "body")
            return message
        request._receive = limited_receive
        try:
            return await call_next(request)
        except Exception as exc:
            logging.warning("RAGFLOW_DEV_REQUEST_FAILED class=%s", type(exc).__name__)
            return JSONResponse({"error": "SERVICE_UNAVAILABLE"}, status_code=503)

    @app.exception_handler(EngineError)
    async def engine_error(request, exc):
        code = 403 if exc.code == "UNAUTHORIZED_SCOPE" else 409 if exc.code in (
            "STALE_VERSION", "CONCURRENT_MODIFICATION") else 404 if exc.code == "SOURCE_NOT_FOUND" else (
            413 if exc.code in ("CAPACITY_EXCEEDED", "INPUT_TOO_LARGE") else 422 if exc.code == "PARSER_FAILED" else 503)
        return JSONResponse({"error": exc.code, "stage": exc.stage}, status_code=code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"error": "INVALID_INPUT"}, status_code=422)

    def principal(authorization: str = Header(default="")):
        credential = authorization[7:] if authorization.startswith("Bearer ") else ""
        s = app.state.settings
        if secrets.compare_digest(credential, s.token_a):
            return "a"
        if secrets.compare_digest(credential, s.token_b):
            return "b"
        raise HTTPException(status_code=401, detail="UNAUTHORIZED")

    def admin(authorization: str = Header(default="")):
        credential = authorization[7:] if authorization.startswith("Bearer ") else ""
        if not secrets.compare_digest(credential, app.state.settings.admin_token):
            raise HTTPException(status_code=401, detail="UNAUTHORIZED")

    @app.get("/health", include_in_schema=False)
    @app.get("/ragflow-dev/health")
    def health():
        result = app.state.runtime.health()
        return JSONResponse(result, status_code=200 if result["healthy"] else 503)

    @app.get("/ragflow-dev/sources")
    def sources(tenant=Depends(principal)):
        return app.state.runtime.status(tenant)

    @app.post("/ragflow-dev/ingest")
    def ingest(payload: Ingest, tenant=Depends(principal)):
        return app.state.runtime.ingest(tenant, payload)

    @app.post("/ragflow-dev/retrieve")
    @app.post("/ragflow-dev/context")
    def retrieve(payload: Query, tenant=Depends(principal)):
        return app.state.runtime.retrieve(tenant, payload)

    @app.delete("/ragflow-dev/source/{source_id}")
    def delete(source_id: str, payload: Delete, tenant=Depends(principal)):
        return app.state.runtime.delete(tenant, source_id, payload.expected_version)

    @app.post('/ragflow-dev/compile')
    def compile_artifacts(payload: Compile, tenant=Depends(principal)):
        return app.state.runtime.compile(tenant, payload)

    @app.post('/ragflow-dev/advanced')
    def advanced(payload: AdvancedQuery, tenant=Depends(principal)):
        return app.state.runtime.advanced(tenant, payload)

    @app.post("/ragflow-dev/failure-check", dependencies=[Depends(admin)])
    def failure_check(payload: Fault):
        # Admin-only, request-local injected exception; never alters a real client/model.
        return app.state.runtime.retrieve("a", Query(query=payload.query, trace=True), fault=payload.fault)

    return app


app = create_app()
