"""Indexed, scoped PostgreSQL lexical recall. No ILIKE or provider fallback."""
from dataclasses import dataclass

from sqlalchemy import func, literal_column, select, true

from database.models import Chunk, Document
from services.hybrid_retrieval import ChannelCandidate, FTS_CONFIGURATION
from services.knowledge_scope import ready_chunks


# Must match migration 20260910_01 exactly. Fixed literals are application-owned,
# not caller-controlled: neither default_text_search_config nor prepared-plan
# parameter choices may silently select an expression different from the GIN.
def content_vector():
    assert FTS_CONFIGURATION == "english"
    return func.to_tsvector(literal_column("'english'::regconfig"),
                            func.coalesce(Chunk.content, literal_column("''")))


@dataclass(frozen=True)
class FTSResult:
    candidates: tuple[ChannelCandidate, ...] = ()
    query_status: str = "empty"


def fts_statement(db, query_text, bot_id, organization_id, document_ids, profile, limit):
    if not isinstance(query_text, str) or len(query_text) > 8192:
        raise ValueError("FTS query must be text of at most 8192 characters")
    if type(limit) is not int or not 1 <= limit <= 2000:
        raise ValueError("FTS candidate limit must be from 1 to 2000")
    # MATERIALIZED prevents repeated parsing for scoring/guards/candidate rows.
    parsed = select(func.websearch_to_tsquery(
        literal_column("'english'::regconfig"), query_text).label("query")
    ).cte("fts_input").prefix_with("MATERIALIZED")
    vector = content_vector()
    score = func.ts_rank_cd(vector, parsed.c.query).label("fts_score")
    nodes, tree = func.numnode(parsed.c.query), func.querytree(parsed.c.query)
    candidates = ready_chunks(
        db.query(Chunk.id.label("chunk_id"), Document.id.label("document_id"), score)
        .select_from(Chunk).join(Document, Chunk.document_id == Document.id).join(parsed, true()),
        bot_id, organization_id, document_ids,
    ).filter(
        Chunk.embedding_provider == profile.provider, Chunk.embedding_model == profile.model,
        Chunk.embedding_version == profile.version,
        nodes > 0, tree.notin_(["", "T"]), vector.op("@@")(parsed.c.query),
    ).order_by(score.desc(), Document.id, Chunk.id).limit(limit).cte("fts_candidates")
    # A sentinel row preserves empty/non-indexable vs successful no-match status
    # without a second tsquery call or loading any chunk text into Python.
    return select(candidates.c.chunk_id, candidates.c.document_id, candidates.c.fts_score,
                  nodes.label("nodes"), tree.label("indexable_tree"))\
        .select_from(parsed.outerjoin(candidates, true()))\
        .order_by(candidates.c.fts_score.desc(), candidates.c.document_id, candidates.c.chunk_id)


def fts_candidates(session_factory, query_text, bot_id, organization_id, document_ids, profile, limit):
    with session_factory() as db:
        rows = db.execute(fts_statement(db, query_text, bot_id, organization_id, document_ids, profile, limit)).all()
    if not rows or not rows[0].nodes:
        return FTSResult(query_status="empty")
    if rows[0].indexable_tree in {"", "T"}:
        return FTSResult(query_status="non_indexable")
    result = tuple(ChannelCandidate(int(row.chunk_id), int(row.document_id), float(row.fts_score), rank,
                                    "postgres_fts")
                   for rank, row in enumerate((r for r in rows if r.chunk_id is not None), 1))
    return FTSResult(result, "indexable")
