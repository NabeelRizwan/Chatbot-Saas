"""Internal development engine seam. Public chat routes keep the accepted default.

No env reads, DB calls, provider calls or heavy engine imports at module import.
The selection comes from operator-owned configuration, never request/model text.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class EngineSelection:
    name: str = "current"
    environment: str = "development"
    development_opt_in: bool = False

    def validate(self):
        if self.name not in {"current", "ragflow"}:
            raise ValueError("Unknown RAG engine")
        if self.name == "ragflow" and (self.environment != "development" or not self.development_opt_in):
            raise PermissionError("RAGFlow engine is development-only and requires explicit opt-in")


class CurrentRagEngineAdapter:
    def answer(self, **kwargs):
        from services.rag_service import answer_question
        return answer_question(**kwargs)


class RagFlowDerivedEngineAdapter:
    def __init__(self, engine, authorize):
        self.engine, self.authorize = engine, authorize

    async def answer(self, *, db, bot, question, history=None, top_k=12, **kwargs):
        # authorize is a trusted server callback, not a field from the request.
        scope = self.authorize(db, bot)
        evidence = await self.engine.retrieve(scope, question, top_k=top_k)
        pack = self.engine.build_context(scope, evidence)
        if not pack["evidence"]:
            return "I don't have enough information to answer that yet.", [], []
        from services.rag_service import _get_system_instruction, DEFAULT_SUPPORT_PROMPT, build_rag_prompt
        from services.llm_router import generate
        # Use the existing bot instruction and generation provider. Evidence stays
        # in the prompt's data/context section, never injected as system instructions.
        prompt = build_rag_prompt(question=question, retrieved=[], history=history,
                                  compressed_context=pack["context"])
        system = _get_system_instruction(bot, DEFAULT_SUPPORT_PROMPT, strict_grounding=False)
        reply = generate(bot=bot, prompt=prompt, system_instruction=system)
        self.engine._scope(scope)  # Revocation check before returning any evidence/answer.
        chunks = [{"chunk_id": e.chunk_id, "document_id": e.document_id, "content": e.text,
                   "score": e.similarity, "citation_id": e.citation_id} for e in pack["evidence"]]
        return reply, pack["sources"], chunks


def select_engine(selection=None, *, ragflow_factory=None):
    selection = selection or EngineSelection()
    selection.validate()
    if selection.name == "current":
        return CurrentRagEngineAdapter()
    if ragflow_factory is None:
        raise RuntimeError("RAGFlow development backend is not configured")
    return ragflow_factory()


def ready_platform_scope(db, bot, *, generation, embedding_profile, dimension):
    """Translate existing lifecycle authority, not query/model-derived identifiers.

    Call only after the normal platform get_bot_or_404/get_owned_bot authorization.
    For every request/check caller must re-resolve this snapshot using a fresh
    session; SQLAlchemy sessions must not be shared across upstream worker threads.
    """
    from services.knowledge_scope import ready_documents
    from ragflow_derived.contracts import AuthorizedScope, SourceRef
    rows = ready_documents(db, bot.id, bot.organization_id).all()
    sources = tuple(SourceRef(str(d.id), str(d.id), f"{d.version}.{d.crawl_id or 0}") for d in rows)
    return AuthorizedScope(str(bot.organization_id), str(bot.id), str(generation),
                           embedding_profile, dimension, sources)
