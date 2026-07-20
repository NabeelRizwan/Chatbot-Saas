from fastapi import HTTPException
from sqlalchemy.orm import Session

from database.models import Bot, User
from schemas.schemas import BotCreate, BotUpdate
from services.organization_service import require_org_role
from services.platform_key_service import allocate_key_to_bot, release_key_from_bot
from services.usage_service import ensure_can_create_bot, refresh_resource_usage
from utils.helpers import get_customer_by_api_key

SUPPORTED_MODELS = {
    "gemini": {"gemini-2.5-flash", "gemini-1.5-pro"},
    "openai": {"gpt-4.1-mini", "gpt-4.1"},
    "claude": {"claude-3-5-sonnet", "claude-3-opus"},
    "grok": {"grok-2", "grok-beta"},
}


def mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if "****" in value:
        return value
    prefix = "sk-" if value.startswith("sk-") else value[:4]
    suffix = value[-4:] if len(value) >= 4 else value
    return f"{prefix}{'*' * 8}{suffix}"


def validate_provider_model(provider: str, model_name: str) -> None:
    supported_models = SUPPORTED_MODELS.get(provider)
    if not supported_models:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported provider '{provider}'. Supported providers: {', '.join(sorted(SUPPORTED_MODELS))}.",
        )
    if model_name not in supported_models:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported model '{model_name}' for provider '{provider}'. Supported models: {', '.join(sorted(supported_models))}.",
        )


def serialize_bot(bot: Bot) -> dict:
    customer_api_key = bot.customer.api_key if bot.customer else None

    # Show a masked indicator if bot uses a platform key
    from database.models import PlatformApiKey
    db = Session.object_session(bot)
    platform_key_assigned = False
    if db:
        pk = db.query(PlatformApiKey).filter(PlatformApiKey.allocated_to_bot_id == bot.id).first()
        if pk:
            platform_key_assigned = True

    return {
        "bot_id": bot.id,
        "id": bot.id,
        "name": bot.name,
        "api_key": mask_secret(customer_api_key),
        "provider": bot.provider,
        "model_name": bot.model_name,
        # Show masked custom key, or "platform_managed" indicator, never the actual platform key
        "provider_api_key": mask_secret(bot.provider_api_key) if bot.provider_api_key else (
            "platform_managed" if platform_key_assigned else None
        ),
        "uses_platform_key": platform_key_assigned and not bot.provider_api_key,
        "organization_id": bot.organization_id,
        "system_prompt": bot.system_prompt,
        "welcome_message": bot.welcome_message,
        "widget_config": bot.widget_config,
        "description": bot.description,
        "category": bot.category or "general",
        "avatar_url": bot.avatar_url,
        "status": bot.status or "active",
        "tone": bot.tone or "neutral",
        "capabilities": bot.capabilities or {"web_search": False, "file_analysis": True},
        "created_at": bot.created_at,
    }


def list_bots(db: Session, user: User | None = None, organization_id: int | None = None) -> list[dict]:
    query = db.query(Bot)
    if user and organization_id:
        require_org_role(db, user, organization_id, "viewer")
        query = query.filter(Bot.organization_id == organization_id)
    elif user:
        memberships = [membership.organization_id for membership in user.memberships]
        query = query.filter(Bot.organization_id.in_(memberships))
    else:
        query = query.filter(Bot.organization_id.is_(None))
    bots = query.order_by(Bot.created_at.desc(), Bot.id.desc()).all()
    return [serialize_bot(bot) for bot in bots]


def get_bot_or_404(db: Session, bot_id: int, user: User | None = None, minimum_role: str = "viewer") -> Bot:
    bot = db.query(Bot).filter(Bot.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    if bot.organization_id:
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required")
        require_org_role(db, user, bot.organization_id, minimum_role)
    return bot


def get_bot(db: Session, bot_id: int, user: User | None = None) -> dict:
    return serialize_bot(get_bot_or_404(db, bot_id, user=user))


def create_bot(db: Session, data: BotCreate, user: User | None = None) -> dict:
    validate_provider_model(data.provider, data.model_name)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Ensure user has a customer record (auto-create if missing)
    if not user.customer_id:
        import secrets
        from database.models import Customer
        api_key = secrets.token_hex(16)
        customer = Customer(name=user.name, api_key=api_key)
        db.add(customer)
        db.flush()
        user.customer_id = customer.id
        db.commit()

    organization_id = data.organization_id
    if organization_id:
        require_org_role(db, user, organization_id, "editor")
        ensure_can_create_bot(db, organization_id)

    bot = Bot(
        name=data.name,
        customer_id=user.customer_id,
        organization_id=organization_id,
        system_prompt=data.system_prompt,
        welcome_message=data.welcome_message,
        provider=data.provider,
        model_name=data.model_name,
        provider_api_key=data.provider_api_key.strip() if data.provider_api_key and data.provider_api_key.strip() else None,
        description=data.description,
        category=data.category or "general",
        avatar_url=data.avatar_url,
        status=data.status or "active",
        tone=data.tone or "neutral",
        capabilities=data.capabilities or {"web_search": False, "file_analysis": True},
    )
    db.add(bot)
    db.flush()

    # If no custom key, allocate a platform-managed key.
    # allocate_key_to_bot raises HTTP 400 with user-friendly message if none available.
    if not bot.provider_api_key:
        try:
            allocate_key_to_bot(db, bot)
        except HTTPException:
            # Fallback to transitioned global key if pool is empty
            pass

    db.commit()
    db.refresh(bot)
    if organization_id:
        refresh_resource_usage(db, organization_id)

    return serialize_bot(bot)


def update_bot(db: Session, bot_id: int, data: BotUpdate, user: User | None = None) -> dict:
    bot = get_bot_or_404(db, bot_id, user=user, minimum_role="editor" if user else "member")
    update_data = data.dict(exclude_unset=True)

    next_provider = update_data.get("provider", bot.provider)
    next_model = update_data.get("model_name", bot.model_name)
    validate_provider_model(next_provider, next_model)

    # Determine whether the bot will have a custom key after this update
    has_custom_key = False
    if "provider_api_key" in update_data:
        pval = update_data["provider_api_key"]
        if pval and pval.strip() and "****" not in pval and pval != "platform_managed":
            has_custom_key = True
        elif "****" in str(pval or ""):
            # Masked value submitted — treat as "keep existing custom key"
            has_custom_key = bot.provider_api_key is not None
        else:
            has_custom_key = False
    else:
        has_custom_key = bot.provider_api_key is not None

    provider_changed = next_provider != bot.provider
    was_platform_managed = bot.provider_api_key is None
    switched_to_custom = has_custom_key and was_platform_managed
    switched_to_platform = (not has_custom_key) and (not was_platform_managed)

    # Release platform key when switching to BYOK or when provider changes under platform mode
    if switched_to_custom or (provider_changed and was_platform_managed):
        release_key_from_bot(db, bot.id)

    # Apply field updates
    if "name" in update_data and update_data["name"] is not None:
        bot.name = update_data["name"]
    if "provider" in update_data and update_data["provider"] is not None:
        bot.provider = update_data["provider"]
    if "model_name" in update_data and update_data["model_name"] is not None:
        bot.model_name = update_data["model_name"]
    if "system_prompt" in update_data:
        bot.system_prompt = update_data["system_prompt"]
    if "welcome_message" in update_data:
        bot.welcome_message = update_data["welcome_message"]
    if "widget_config" in update_data:
        bot.widget_config = update_data["widget_config"]
    if "description" in update_data:
        bot.description = update_data["description"]
    if "category" in update_data:
        bot.category = update_data["category"]
    if "avatar_url" in update_data:
        bot.avatar_url = update_data["avatar_url"]
    if "status" in update_data:
        bot.status = update_data["status"]
    if "tone" in update_data:
        bot.tone = update_data["tone"]
    if "capabilities" in update_data:
        bot.capabilities = update_data["capabilities"]

    # Update custom API key
    if "provider_api_key" in update_data:
        pval = update_data["provider_api_key"]
        if pval and pval.strip() and "****" not in str(pval) and pval != "platform_managed":
            bot.provider_api_key = pval.strip()
        elif not pval or not str(pval).strip() or pval == "platform_managed":
            bot.provider_api_key = None

    db.flush()

    # Allocate new platform key if needed
    if not has_custom_key and (switched_to_platform or provider_changed):
        try:
            allocate_key_to_bot(db, bot)
        except HTTPException:
            # Fallback to transitioned global key if pool is empty
            pass

    db.commit()
    db.refresh(bot)
    return serialize_bot(bot)


def delete_bot(db: Session, bot_id: int, user: User | None = None) -> dict:
    bot = get_bot_or_404(db, bot_id, user=user, minimum_role="admin" if user else "member")
    organization_id = bot.organization_id

    # Release any allocated platform key before deleting
    release_key_from_bot(db, bot.id)

    db.delete(bot)
    db.commit()
    if organization_id:
        refresh_resource_usage(db, organization_id)
    return {
        "success": True,
        "bot_id": bot_id,
        "message": "Bot deleted successfully",
    }


def clone_bot(db: Session, bot_id: int, user: User | None = None) -> dict:
    original = get_bot_or_404(db, bot_id, user=user, minimum_role="editor")

    if original.organization_id:
        ensure_can_create_bot(db, original.organization_id)

    cloned = Bot(
        name=f"Copy of {original.name}",
        customer_id=original.customer_id,
        organization_id=original.organization_id,
        system_prompt=original.system_prompt,
        welcome_message=original.welcome_message,
        provider=original.provider,
        model_name=original.model_name,
        # Clone never inherits platform key — it gets its own allocation
        provider_api_key=original.provider_api_key,
        widget_config=original.widget_config,
        description=original.description,
        category=original.category,
        avatar_url=original.avatar_url,
        status="active",
        tone=original.tone,
        capabilities=original.capabilities,
    )
    db.add(cloned)
    db.flush()

    # Allocate platform key for cloned bot if original used platform managed
    if not original.provider_api_key:
        try:
            allocate_key_to_bot(db, cloned)
        except HTTPException:
            # If no keys available, clone succeeds but operates without a key
            pass

    from database.models import Document, Chunk
    docs = db.query(Document).filter(Document.bot_id == original.id).all()
    for doc in docs:
        cloned_doc = Document(
            bot_id=cloned.id,
            organization_id=doc.organization_id,
            filename=doc.filename,
            source_type=doc.source_type,
            source_url=doc.source_url,
            title=doc.title,
            raw_text=doc.raw_text,
            file_path=doc.file_path,
            file_size=doc.file_size,
            processing_status=doc.processing_status,
            processing_error=doc.processing_error,
            chunk_count=doc.chunk_count,
            token_count=doc.token_count,
            metadata_json=doc.metadata_json,
        )
        db.add(cloned_doc)
        db.flush()

        chunks = db.query(Chunk).filter(Chunk.document_id == doc.id).all()
        for chunk in chunks:
            cloned_chunk = Chunk(
                document_id=cloned_doc.id,
                bot_id=cloned.id,
                organization_id=chunk.organization_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                embedding=chunk.embedding,
                metadata_json=chunk.metadata_json,
                token_count=chunk.token_count,
            )
            db.add(cloned_chunk)

    db.commit()
    db.refresh(cloned)

    if original.organization_id:
        refresh_resource_usage(db, original.organization_id)

    return serialize_bot(cloned)
