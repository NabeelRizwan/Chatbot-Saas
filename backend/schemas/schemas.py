from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl

ProviderName = Literal["gemini", "openai", "claude", "grok"]


class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class CustomerResponse(BaseModel):
    api_key: str


class BotCreate(BaseModel):
    organization_id: Optional[int] = None
    name: str = Field(..., min_length=1, max_length=120)
    provider: ProviderName = "gemini"
    model_name: str = Field(default="gemini-2.5-flash", min_length=1, max_length=120)
    provider_api_key: Optional[str] = None
    system_prompt: Optional[str] = None
    welcome_message: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = "general"
    avatar_url: Optional[str] = None
    status: Optional[str] = "active"
    tone: Optional[str] = "neutral"
    capabilities: Optional[dict] = Field(default_factory=lambda: {"web_search": False, "file_analysis": True})


class BotResponse(BaseModel):
    bot_id: int
    name: str
    provider: str
    model_name: str
    id: Optional[int] = None
    api_key: Optional[str] = None
    provider_api_key: Optional[str] = None
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


class BotUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    provider: Optional[ProviderName] = None
    model_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    provider_api_key: Optional[str] = None
    system_prompt: Optional[str] = None
    welcome_message: Optional[str] = None
    widget_config: Optional[dict] = None
    description: Optional[str] = None
    category: Optional[str] = None
    avatar_url: Optional[str] = None
    status: Optional[str] = None
    tone: Optional[str] = None
    capabilities: Optional[dict] = None


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


class KnowledgeDocumentResponse(BaseModel):
    id: int
    bot_id: int
    filename: str
    source_type: str
    source_url: Optional[str] = None
    file_size: Optional[int] = None
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


class KnowledgeDeleteResponse(BaseModel):
    success: bool
    document_id: int
    message: str


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
    refresh_token: str = Field(..., min_length=20)


class AuthLogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


class AuthTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
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
    role: Literal["admin", "member"] = "member"


class InvitationCreateRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    role: Literal["admin", "member"] = "member"


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
    usage: dict[str, int]
    limits: dict[str, int]
    subscription_status: str
