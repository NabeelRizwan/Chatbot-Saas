from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database.models import Bot, User
from schemas.schemas import BotCreate, BotUpdate
from services.organization_service import require_org_role
from services.platform_key_service import allocate_key_to_bot, release_key_from_bot, lock_credential_lifecycle
from services.usage_service import (
    ensure_can_create_bot,
    ensure_can_promote_knowledge,
    refresh_resource_usage,
)
from services.public_access_service import normalize_allowed_origins
from services.tenant_cache_service import invalidate_bot_cache
from services.bot_secret_service import (
    encrypt_bot_provider_key,
    is_encrypted_bot_key,
    mask_bot_provider_key,
)
from services.object_storage import (
    ObjectStorageError,
    build_source_object_key,
    get_object_storage,
    validate_source_object_ownership,
)

SUPPORTED_MODELS = {
    "gemini": {"gemini-2.5-flash", "gemini-1.5-pro"},
    "openai": {"gpt-4.1-mini", "gpt-4.1"},
    "claude": {"claude-3-5-sonnet", "claude-3-opus"},
    "grok": {"grok-2", "grok-beta"},
}

UNSCOPED_BOT_DETAIL = (
    "This legacy bot is not assigned to an organization and cannot be accessed "
    "from authenticated tenant routes until an administrator backfills its ownership."
)


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

    return {
        "bot_id": bot.id,
        "id": bot.id,
        "name": bot.name,
        "api_key": mask_secret(customer_api_key),
        "provider": bot.provider,
        "model_name": bot.model_name,
        "provider_api_key_masked": mask_bot_provider_key(bot.provider_api_key),
        "ai_usage_mode": "byo" if bot.provider_api_key else "platform",
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
        "allowed_origins": bot.allowed_origins or [],
        "created_at": bot.created_at,
    }


def require_bot_organization(bot: Bot) -> int:
    """Fail closed for legacy bots that have no tenant owner."""
    if bot.organization_id is None:
        raise HTTPException(status_code=409, detail=UNSCOPED_BOT_DETAIL)
    return bot.organization_id


def update_platform_generation_config(db: Session, bot: Bot, provider: str,
                                      model_name: str, credential_id: int | None,
                                      actor_user_id: int | None = None) -> None:
    """Admin-only caller owns authorization and transaction; reuse bot validation.

    Only generation fields and the existing credential references are changed.
    BYOK remains in the customer's authorized workflow. No knowledge writes.
    Null removes the assignment, or auto-allocates when changing provider.
    """
    from services.platform_key_service import assign_key_to_bot

    require_bot_organization(bot)
    if bot.provider_api_key:
        raise HTTPException(status_code=409, detail="This bot uses customer BYOK. Ask its owner to switch to platform mode first.")
    validate_provider_model(provider, model_name)
    provider_changed = bot.provider != provider
    bot.provider = provider
    bot.model_name = model_name
    if credential_id is None:
        release_key_from_bot(db, bot.id, actor_user_id)
        if provider_changed:
            allocate_key_to_bot(db, bot, actor_user_id)
    else:
        assign_key_to_bot(db, credential_id, bot, actor_user_id)
    db.flush()


def list_bots(db: Session, user: User | None = None, organization_id: int | None = None) -> list[dict]:
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    query = db.query(Bot)
    if organization_id is not None:
        require_org_role(db, user, organization_id, "viewer")
        query = query.filter(Bot.organization_id == organization_id)
    else:
        memberships = [membership.organization_id for membership in user.memberships]
        query = query.filter(Bot.organization_id.in_(memberships))
    bots = query.order_by(Bot.created_at.desc(), Bot.id.desc()).all()
    return [serialize_bot(bot) for bot in bots]


def get_bot_or_404(db: Session, bot_id: int, user: User | None = None, minimum_role: str = "viewer") -> Bot:
    bot = db.query(Bot).filter(Bot.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    organization_id = require_bot_organization(bot)
    require_org_role(db, user, organization_id, minimum_role)
    return bot


def get_bot(db: Session, bot_id: int, user: User | None = None) -> dict:
    return serialize_bot(get_bot_or_404(db, bot_id, user=user))


def create_bot(db: Session, data: BotCreate, user: User | None = None) -> dict:
    validate_provider_model(data.provider, data.model_name)
    try:
        allowed_origins = normalize_allowed_origins(data.allowed_origins)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    organization_id = data.organization_id
    if organization_id is None:
        raise HTTPException(status_code=422, detail="organization_id is required to create a bot")
    require_org_role(db, user, organization_id, "editor")
    ensure_can_create_bot(db, organization_id)

    # Ensure user has a customer record (auto-create if missing)
    if not user.customer_id:
        import secrets
        from database.models import Customer
        api_key = secrets.token_hex(16)
        customer = Customer(name=user.name, api_key=api_key)
        db.add(customer)
        db.flush()
        user.customer_id = customer.id
        # Keep the subscription quota lock until the Bot row is committed.
        db.flush()

    bot = Bot(
        name=data.name,
        customer_id=user.customer_id,
        organization_id=organization_id,
        system_prompt=data.system_prompt,
        welcome_message=data.welcome_message,
        widget_config=data.widget_config.model_dump() if data.widget_config else {},
        provider=data.provider,
        model_name=data.model_name,
        provider_api_key=(
            encrypt_bot_provider_key(data.provider_api_key)
            if data.provider_api_key and data.provider_api_key.strip()
            else None
        ),
        description=data.description,
        category=data.category,
        avatar_url=data.avatar_url,
        status=data.status,
        tone=data.tone,
        capabilities=data.capabilities.model_dump(),
        allowed_origins=allowed_origins,
    )
    db.add(bot)
    db.flush()

    # Creation may succeed unassigned; generation then fails closed until provisioned.
    if not bot.provider_api_key:
        allocate_key_to_bot(db, bot, user.id)

    db.commit()
    db.refresh(bot)
    refresh_resource_usage(db, organization_id)

    return serialize_bot(bot)


def update_bot(db: Session, bot_id: int, data: BotUpdate, user: User | None = None) -> dict:
    lock_credential_lifecycle(db)
    bot = get_bot_or_404(db, bot_id, user=user, minimum_role="editor" if user else "member")
    if bot.provider_api_key and not is_encrypted_bot_key(bot.provider_api_key):
        # Controlled encrypt-on-write for a legacy row. The explicit migration
        # script should still be run before disabling legacy reads in production.
        bot.provider_api_key = encrypt_bot_provider_key(bot.provider_api_key)
    update_data = data.model_dump(exclude_unset=True)
    if "allowed_origins" in update_data:
        try:
            update_data["allowed_origins"] = normalize_allowed_origins(update_data["allowed_origins"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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
        release_key_from_bot(db, bot.id, user.id if user else None)

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
    if "allowed_origins" in update_data:
        bot.allowed_origins = update_data["allowed_origins"]

    # Update custom API key
    if "provider_api_key" in update_data:
        pval = update_data["provider_api_key"]
        if pval and pval.strip() and "****" not in str(pval) and pval != "platform_managed":
            bot.provider_api_key = encrypt_bot_provider_key(pval)
        elif not pval or not str(pval).strip() or pval == "platform_managed":
            bot.provider_api_key = None

    db.flush()

    # Allocate new platform key if needed
    if not has_custom_key and (switched_to_platform or provider_changed):
        allocate_key_to_bot(db, bot, user.id if user else None)

    db.commit()
    db.refresh(bot)
    invalidate_bot_cache(bot.id, bot.organization_id)
    return serialize_bot(bot)


def delete_bot(db: Session, bot_id: int, user: User | None = None) -> dict:
    lock_credential_lifecycle(db)
    bot = get_bot_or_404(db, bot_id, user=user, minimum_role="admin" if user else "member")
    organization_id = bot.organization_id

    # Release any allocated platform key before deleting
    release_key_from_bot(db, bot.id, user.id if user else None)

    db.delete(bot)
    db.commit()
    refresh_resource_usage(db, organization_id)
    return {
        "success": True,
        "bot_id": bot_id,
        "message": "Bot deleted successfully",
    }


def clone_bot(db: Session, bot_id: int, user: User | None = None) -> dict:
    original = get_bot_or_404(db, bot_id, user=user, minimum_role="editor")
    organization_id = require_bot_organization(original)
    ensure_can_create_bot(db, organization_id)
    from database.models import Document, Chunk
    docs = db.query(Document).filter(
        Document.bot_id == original.id,
        Document.status == "ready",
    ).all()
    ensure_can_promote_knowledge(
        db,
        organization_id,
        resulting_documents=len(docs),
        resulting_storage_bytes=sum(doc.logical_size_bytes or 0 for doc in docs),
    )

    cloned = Bot(
        name=f"Copy of {original.name}",
        customer_id=original.customer_id,
        organization_id=organization_id,
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
        allowed_origins=list(original.allowed_origins or []),
    )
    db.add(cloned)
    db.flush()

    # Allocate platform key for cloned bot if original used platform managed
    if not original.provider_api_key:
        allocate_key_to_bot(db, cloned, user.id if user else None)

    copied_objects: list[tuple[str, str]] = []
    try:
        for doc in docs:
            cloned_storage_provider = doc.storage_provider
            cloned_storage_key = doc.storage_key
            if doc.storage_provider and doc.storage_key:
                source_key = validate_source_object_ownership(
                    doc.storage_key,
                    organization_id,
                    original.id,
                )
                storage = get_object_storage(doc.storage_provider)
                extension = Path(source_key).suffix or Path(doc.filename or "").suffix
                cloned_storage_key = build_source_object_key(
                    organization_id,
                    cloned.id,
                    extension,
                )
                with storage.download_to_temp(source_key) as temporary_path:
                    payload = Path(temporary_path).read_bytes()
                stored = storage.put(
                    cloned_storage_key,
                    payload,
                    content_type=doc.content_type,
                    metadata={"organization_id": str(organization_id), "bot_id": str(cloned.id)},
                )
                cloned_storage_key = stored.key
                copied_objects.append((doc.storage_provider, stored.key))

            cloned_doc = Document(
                bot_id=cloned.id,
                organization_id=organization_id,
                filename=doc.filename,
                source_type=doc.source_type,
                source_url=doc.source_url,
                title=doc.title,
                raw_text=doc.raw_text,
                content_hash=doc.content_hash,
                source_content_hash=doc.source_content_hash,
                file_path=doc.file_path,
                file_size=doc.file_size,
                storage_provider=cloned_storage_provider,
                storage_key=cloned_storage_key,
                content_type=doc.content_type,
                original_filename=doc.original_filename,
                logical_size_bytes=doc.logical_size_bytes,
                processing_status=doc.processing_status,
                processing_error=doc.processing_error,
                chunk_count=doc.chunk_count,
                token_count=doc.token_count,
                embedding_provider=doc.embedding_provider,
                embedding_model=doc.embedding_model,
                embedding_version=doc.embedding_version,
                embedding_dimensions=doc.embedding_dimensions,
                metadata_json=doc.metadata_json,
            )
            db.add(cloned_doc)
            db.flush()

            chunks = db.query(Chunk).filter(Chunk.document_id == doc.id).all()
            for chunk in chunks:
                cloned_chunk = Chunk(
                    document_id=cloned_doc.id,
                    bot_id=cloned.id,
                    organization_id=organization_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    embedding=chunk.embedding,
                    metadata_json=chunk.metadata_json,
                    token_count=chunk.token_count,
                    status=chunk.status,
                    embedding_provider=chunk.embedding_provider,
                    embedding_model=chunk.embedding_model,
                    embedding_version=chunk.embedding_version,
                )
                db.add(cloned_chunk)

        db.commit()
    except Exception:
        db.rollback()
        for storage_provider, storage_key in copied_objects:
            try:
                get_object_storage(storage_provider).delete(storage_key)
            except ObjectStorageError:
                pass
        raise
    db.refresh(cloned)

    refresh_resource_usage(db, organization_id)

    return serialize_bot(cloned)
