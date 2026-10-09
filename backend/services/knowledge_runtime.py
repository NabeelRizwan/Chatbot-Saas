"""Select one retrieval implementation for chat, ingestion and readiness."""
import os


def engine_name():
    name = os.getenv("KNOWLEDGE_ENGINE", "ragflow").strip().lower()
    if name not in {"llamaindex", "ragflow"}:
        raise ValueError("KNOWLEDGE_ENGINE must be llamaindex or ragflow")
    return name


def answer_question(**kwargs):
    if engine_name() == "llamaindex":
        from services.llama_rag.answer import answer_question as answer
    else:
        from services.native_rag.answer import answer_question as answer
    return answer(**kwargs)


def prepare(*args, **kwargs):
    if engine_name() == "llamaindex":
        from services.llama_rag.ingestion import prepare as prepare_source
    else:
        from services.native_rag.ingestion import prepare as prepare_source
        kwargs.pop("source_url", None)
    return prepare_source(*args, **kwargs)


def promote(db, document, staging_id):
    if engine_name() == "ragflow":
        from services.native_rag.knowledge import promote as promote_native
        promote_native(db, document, staging_id)
    # LlamaIndex derives immutable indexes from atomically promoted Documents.
    # There is no external dataset binding to promote or provider embedding key.


def readiness():
    if engine_name() == "llamaindex":
        from services.llama_rag.client import RetrievalClient
        try:
            result = RetrievalClient().request("/health/ready", method="GET", timeout=3)
            return "ready" if result == {"status": "ready", "engine": "llamaindex", "protocol": 1} else "unavailable"
        except Exception:
            return "unavailable"
    from services.combined_rag.readiness import readiness as ranker
    from services.native_rag.readiness import readiness as native
    return "ready" if native() == ranker() == "ready" else "unavailable"


def warm(db, bot):
    if engine_name() == "llamaindex":
        from services.llama_rag.knowledge import KnowledgeScope
        scope = KnowledgeScope(db, bot)
        if scope.records:
            scope.client.snapshot(scope.payload, scope.records)
            scope.check()


def prepare_corpus(db, bot, replacements, *, replaced_website_id=None):
    """Build the proposed corpus before the existing atomic source promotion."""
    if engine_name() != 'llamaindex':
        return
    from services.llama_rag.knowledge import KnowledgeScope, fingerprint
    from services.llama_rag.client import RetrievalClient
    from services.native_rag.knowledge import ready_documents
    replaced_ids = {record['id'] for record in replacements}
    existing = [document for document in ready_documents(db, bot)
        if str(document.id) not in replaced_ids and
        (replaced_website_id is None or document.website_id != replaced_website_id)]
    records = KnowledgeScope._records(existing)
    records = sorted([*records, *replacements], key=lambda record: int(record['id']))
    payload = {'organization_id': bot.organization_id, 'bot_id': bot.id, 'fingerprint': fingerprint(records)}
    # All staging writes were committed by the caller. Release the read
    # transaction during model work; promotion rechecks cancellation and budgets.
    db.rollback()
    RetrievalClient().snapshot(payload, records)
