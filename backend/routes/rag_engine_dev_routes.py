"""Explicitly installed development-only router; main.py does not mount it.

Uses existing login, bot authorization and message quota. No credential fields,
client-selected engine, source IDs, organizations or scope in request bodies.
"""
import inspect
from fastapi import APIRouter, Depends, HTTPException
from services.rag_engine_adapters import EngineSelection, select_engine


def create_router(selection: EngineSelection, ragflow_factory):
    selection.validate()
    if selection.environment != "development" or not selection.development_opt_in:
        raise PermissionError("Explicit development-only installation required")
    from database.connection import get_db
    from services.auth_service import get_current_user
    from services.bot_service import get_bot_or_404
    from services.usage_service import ensure_can_send_message, consume_message_quota, release_message_quota
    from schemas.schemas import PublicChatRequest
    from ragflow_derived.contracts import EngineError
    router = APIRouter(prefix="/internal/development/rag", tags=["development-rag"])
    adapter = select_engine(selection, ragflow_factory=ragflow_factory)

    @router.post("/{bot_id}")
    async def answer(bot_id: int, data: PublicChatRequest,
                     current_user=Depends(get_current_user), db=Depends(get_db)):
        bot = get_bot_or_404(db, bot_id, user=current_user, minimum_role="viewer")
        usage = ensure_can_send_message(db, bot.organization_id)
        try:
            result = adapter.answer(db=db, bot=bot, question=data.message, history=data.history,
                                    top_k=data.top_k)
            if inspect.isawaitable(result):
                result = await result
            reply, sources, chunks = result
            consume_message_quota(db, bot.organization_id, usage)
            return {"reply": reply, "answer": reply, "sources": sources, "retrieved_chunks": chunks}
        except Exception as exc:
            release_message_quota(db, bot.organization_id, usage)
            if isinstance(exc, EngineError):
                raise HTTPException(status_code=403 if exc.code == "UNAUTHORIZED_SCOPE" else 503,
                                    detail={"code": exc.code}) from None
            raise
    return router
