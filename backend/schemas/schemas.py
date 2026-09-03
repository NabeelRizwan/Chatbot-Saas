from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

ProviderName = Literal["gemini", "openai", "claude", "grok"]
BotStatusName = Literal["active", "draft", "disabled"]
BotToneName = Literal["professional", "friendly", "empathetic", "humorous", "neutral"]
BotCategoryName = Literal["general", "sales", "marketing", "hr"]


class BotCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    web_search: bool = False
    file_analysis: bool = True
    temperature: float = Field(default=0.7, ge=0.1, le=1.0)


class BotWidgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    welcome_message: str = Field(default="Hi, how can I help you today?", max_length=500)
    primary_color: str = Field(default="#2563eb", pattern=r"^#[0-9a-fA-F]{6}$")
    accent_color: str = Field(default="#0f172a", pattern=r"^#[0-9a-fA-F]{6}$")
    launcher_text: str = Field(default="Chat", min_length=1, max_length=80)
    launcher_icon: Literal["message", "bot", "support"] = "message"
    position: Literal["bottom-right", "bottom-left"] = "bottom-right"
    placeholder_text: str = Field(default="Type your message...", min_length=1, max_length=160)


class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class CustomerResponse(BaseModel):
    api_key: str


class BotCreate(BaseModel):
    organization_id: int = Field(..., gt=0)
    name: str = Field(..., min_length=1, max_length=120)
    provider: ProviderName = "gemini"
    model_name: str = Field(default="gemini-2.5-flash", min_length=1, max_length=120)
    provider_api_key: Optional[str] = None
    system_prompt: Optional[str] = Field(default=None, max_length=10000)
    welcome_message: Optional[str] = Field(default=None, max_length=500)
    widget_config: Optional[BotWidgetConfig] = None
    description: Optional[str] = Field(default=None, max_length=2000)
    category: BotCategoryName = "general"
    avatar_url: Optional[str] = Field(default=None, max_length=2048)
    status: BotStatusName = "active"
    tone: BotToneName = "neutral"
    capabilities: BotCapabilities = Field(default_factory=BotCapabilities)
    allowed_origins: list[str] = Field(default_factory=list, max_length=100)


class BotResponse(BaseModel):
    bot_id: int
    name: str
    provider: str
    model_name: str
    id: Optional[int] = None
    api_key: Optional[str] = None
    provider_api_key_masked: Optional[str] = None
    ai_usage_mode: Literal["platform", "byo"] = "platform"
    organization_id: Optional[int] = None
    system_prompt: Optional[str] = None
    welcome_message: Optional[str] = None
    widget_config: Optional[dict] = None
    created_at: Optional[datetime] = None
    status: str = "active"
    description: Optional[str] = None
    category: Optional[str] = "general"
    avatar_url: Optional[str] = None
    tone: Optional[str] = "neutral"
    capabilities: Optional[dict] = None
    allowed_origins: list[str] = Field(default_factory=list)


class BotUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    provider: Optional[ProviderName] = None
    model_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    provider_api_key: Optional[str] = None
    system_prompt: Optional[str] = Field(default=None, max_length=10000)
    welcome_message: Optional[str] = Field(default=None, max_length=500)
    widget_config: Optional[BotWidgetConfig] = None
    description: Optional[str] = Field(default=None, max_length=2000)
    category: Optional[BotCategoryName] = None
    avatar_url: Optional[str] = Field(default=None, max_length=2048)
    status: Optional[BotStatusName] = None
    tone: Optional[BotToneName] = None
    capabilities: Optional[BotCapabilities] = None
    allowed_origins: Optional[list[str]] = Field(default=None, max_length=100)

    @model_validator(mode="before")
    @classmethod
    def reject_null_non_nullable_fields(cls, values):
        if not isinstance(values, dict):
            return values
        non_nullable = {
            "name", "provider", "model_name", "widget_config", "category",
            "status", "tone", "capabilities", "allowed_origins",
        }
        null_fields = sorted(field for field in non_nullable if field in values and values[field] is None)
        if null_fields:
            raise ValueError(f"Fields cannot be null: {', '.join(null_fields)}")
        return values


class BotDeleteResponse(BaseModel):
    success: bool
    bot_id: int
    message: str


class WebsiteIngestRequest(BaseModel):
    bot_id: int
    url: HttpUrl
    use_playwright: bool = False


class TextIngestRequest(BaseModel):
    bot_id: int
    title: Optional[str] = None
    text: str = Field(..., min_length=1)


class IngestResponse(BaseModel):
    document_id: int
    chunks_created: int


ProcessingStatus = Literal["pending", "processing", "completed", "failed"]
SourceType = Literal["pdf", "txt", "docx", "website", "text"]


class KnowledgeCrawlRequest(BaseModel):
    bot_id: int = Field(..., gt=0)
    url: HttpUrl
    crawl_mode: Literal["recursive", "single_page"] = "recursive"


class KnowledgeDocumentResponse(BaseModel):
    id: int
    bot_id: int
    filename: str
    source_type: str
    source_url: Optional[str] = None
    file_size: Optional[int] = None
    logical_size_bytes: int = 0
    lifecycle_status: str = "ready"
    active: bool = False
    version: int = 1
    page_count: int = 1
    last_indexed_at: Optional[datetime] = None
    processing_status: str
    processing_error: Optional[str] = None
    chunk_count: int
    token_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentListResponse(BaseModel):
    documents: list[KnowledgeDocumentResponse]


class KnowledgeAcceptedResponse(BaseModel):
    document: KnowledgeDocumentResponse
    message: str
    job_id: Optional[str] = None


class CrawlUrlResult(BaseModel):
    url: str
    result: str
    reason: str


class CrawlCoverageResponse(BaseModel):
    discovered: int = 0
    eligible: int = 0
    crawled: int = 0
    indexed: int = 0
    skipped: int = 0
    failed: int = 0
    duplicates: int = 0
    maximum_depth: int = 0
    coverage_percent: Optional[float] = None
    documents: int = 0
    chunks: int = 0
    url_results: list[CrawlUrlResult] = Field(default_factory=list)


class JobResponse(BaseModel):
    job_id: str
    bot_id: int
    source_name: str
    source_url: Optional[str] = None
    ingestion_type: str
    status: str
    stage: str
    progress_percent: Optional[int] = None
    attempt_number: int = 1
    retryable: bool = False
    cancellable: bool = False
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    crawl_coverage: Optional[CrawlCoverageResponse] = None
    active_version: Optional[int] = None
    candidate_version: Optional[int] = None
    version_state: Optional[str] = None
    chunks_created: int = 0


class JobListResponse(BaseModel):
    jobs: list[JobResponse]


class KnowledgeDeleteResponse(BaseModel):
    success: bool
    document_id: int
    message: str
    scope: str = "document"
    deleted_documents: int = 1



class RetrievedChunkResponse(BaseModel):
    chunk_id: int
    document_id: int
    chunk_index: int
    content: str
    token_count: int
    score: float
    source_filename: str
    source_url: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatSourceResponse(BaseModel):
    document_id: int
    filename: str
    source_url: Optional[str] = None
    chunk_refs: list[int]
    title: Optional[str] = None
    source_type: Optional[str] = None
    cta_links: list[dict[str, str]] = Field(default_factory=list)


class ChatRequest(BaseModel):
    api_key: str
    bot_id: int
    message: str = Field(..., min_length=1)
    top_k: int = Field(default=4, ge=1, le=12)
    history: list[dict[str, str]] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    answer: Optional[str] = None
    sources: list[ChatSourceResponse | str]
    retrieved_chunks: list[RetrievedChunkResponse] = Field(default_factory=list)
    latency_ms: Optional[int] = None
    model_name: Optional[str] = None
    provider: Optional[str] = None
    _debug: Optional[dict[str, Any]] = None



class PublicChatRequest(BaseModel):
    session_id: Optional[str] = Field(default=None, max_length=120)
    session_token: Optional[str] = Field(default=None, max_length=200)
    turn_id: Optional[str] = Field(default=None, max_length=120)
    retry: bool = False
    message: str = Field(..., min_length=1)
    top_k: int = Field(default=4, ge=1, le=12)
    history: list[dict[str, str]] = Field(default_factory=list)


class PublicChatResponse(ChatResponse):
    session_id: Optional[str] = None


class PublicWidgetConfigResponse(BaseModel):
    bot_id: int
    bot_name: str
    welcome_message: str
    primary_color: str = "#2563eb"
    accent_color: str = "#0f172a"
    launcher_text: str = "Chat"
    launcher_title: str = "Chat with us"
    launcher_icon: str = "message"
    bot_avatar_url: Optional[str] = None
    position: str = "bottom-right"
    placeholder_text: str = "Type your message..."


class PublicSessionResponse(BaseModel):
    session_id: str
    session_token: str


class PublicTurnAbortRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=120)
    session_token: str = Field(..., min_length=1, max_length=200)
    turn_id: str = Field(..., min_length=1, max_length=120)


class AnalyticsSummaryResponse(BaseModel):
    bot_id: int
    total_conversations: int
    total_messages: int
    average_response_time_ms: Optional[float] = None
    recent_conversations_24h: int
    recent_messages_24h: int
    successful_messages: int
    errored_messages: int
    last_message_at: Optional[datetime] = None


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    preferences: Optional[dict] = None
    is_admin: bool = False


class UserUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    preferences: Optional[dict] = None


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=200)


class AuthRegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=8, max_length=200)
    organization_name: Optional[str] = Field(default=None, max_length=120)


class AuthLoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=200)


class AuthRefreshRequest(BaseModel):
    refresh_token: Optional[str] = Field(default=None, min_length=20)


class AuthLogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


class AuthTokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class OrganizationResponse(BaseModel):
    id: int
    name: str
    slug: str
    role: str
    created_at: datetime


class OrganizationCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class OrganizationUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class OrganizationMemberResponse(BaseModel):
    id: int
    user_id: int
    name: str
    email: str
    role: str
    created_at: datetime


class OrganizationMemberUpdateRequest(BaseModel):
    role: Literal["viewer", "member", "editor", "admin"] = "member"


class InvitationCreateRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    role: Literal["viewer", "member", "editor", "admin"] = "member"


class InvitationResponse(BaseModel):
    id: int
    organization_id: int
    email: str
    role: str
    status: str
    expires_at: datetime
    invite_token: Optional[str] = None


class InvitationDecisionRequest(BaseModel):
    token: str = Field(..., min_length=20)


class PlanResponse(BaseModel):
    code: str
    name: str
    monthly_price_cents: int
    limits: dict[str, int]


class SubscriptionResponse(BaseModel):
    organization_id: int
    plan: PlanResponse
    status: str


class UsageSummaryResponse(BaseModel):
    organization_id: int
    month: str
    current_plan: str
    current_period: dict[str, Optional[str]]
    usage: dict[str, Any]
    limits: dict[str, int]
    metering: dict[str, str]
    subscription_status: str
