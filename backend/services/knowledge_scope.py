"""Database-owned knowledge boundaries shared by planning and chunk recall."""
from sqlalchemy import and_, case, exists, func, or_, tuple_
from sqlalchemy.orm import load_only

from database.models import Chunk, Document, Website, WebsiteCrawl


def ready_chunks(query, bot_id, organization_id, document_ids=None, *, hard_scope=None):
    if organization_id is None:
        return query.filter(False)
    active_crawl = exists().where(and_(
        Website.id == Document.website_id, Website.bot_id == bot_id,
        Website.organization_id == organization_id, Website.status == "ready",
        Website.active_crawl_id == Document.crawl_id,
        WebsiteCrawl.id == Document.crawl_id, WebsiteCrawl.website_id == Website.id,
        WebsiteCrawl.bot_id == bot_id, WebsiteCrawl.organization_id == organization_id,
        WebsiteCrawl.status == "ready", WebsiteCrawl.version == Document.version,
    )).correlate(Document)
    query = query.filter(
        Document.bot_id == bot_id, Document.organization_id == organization_id,
        Document.status == "ready", Document.processing_status == "completed",
        Chunk.document_id == Document.id, Chunk.bot_id == bot_id,
        Chunk.organization_id == organization_id, Chunk.status == "ready",
        or_(
            and_(Document.source_type != "website", Document.website_id.is_(None), Document.crawl_id.is_(None),
                 Chunk.website_id.is_(None), Chunk.crawl_id.is_(None)),
            and_(Chunk.website_id == Document.website_id,
                 Chunk.crawl_id == Document.crawl_id, active_crawl),
        ),
    )
    # None means discovery; [] means a resolved scope is no longer available.
    if document_ids is not None:
        query = query.filter(Document.id.in_(document_ids))
    if hard_scope is not None:
        if hard_scope.bot_id != bot_id or hard_scope.organization_id != organization_id or hard_scope.empty:
            return query.filter(False)
        if hard_scope.authorized_document_ids is not None:
            query = query.filter(Document.id.in_(hard_scope.authorized_document_ids))
        if hard_scope.authorized_source_ids is not None:
            query = query.filter(Document.website_id.in_(hard_scope.authorized_source_ids))
        if hard_scope.active_document_versions:
            requested_ids = set(document_ids) if document_ids is not None else None
            versions = [v for v in hard_scope.active_document_versions if requested_ids is None or v[0] in requested_ids]
            uploads = [(i, version) for i, version, crawl in versions if crawl is None]
            crawls = [(i, version, crawl) for i, version, crawl in versions if crawl is not None]
            query = query.filter(or_(
                and_(Document.crawl_id.is_(None), tuple_(Document.id, Document.version).in_(uploads)),
                tuple_(Document.id, Document.version, Document.crawl_id).in_(crawls),
            ))
        profile = hard_scope.embedding_profile
        if profile is not None:
            query = query.filter(Chunk.embedding_provider == profile.provider,
                                 Chunk.embedding_model == profile.model,
                                 Chunk.embedding_version == profile.version)
    return query


def ready_documents(db, bot_id, organization_id, *, hard_scope=None):
    eligible_chunk = ready_chunks(db.query(Chunk.id), bot_id, organization_id, hard_scope=hard_scope).correlate(Document).exists()
    return db.query(Document).filter(
        Document.bot_id == bot_id, Document.organization_id == organization_id,
        eligible_chunk,
    )


def identity_documents(db, bot_id, organization_id, limit=10001, *, hard_scope=None):
    """Metadata only, bounded independently of chunk count; no embeddings/text."""
    return ready_documents(db, bot_id, organization_id, hard_scope=hard_scope).options(load_only(
        Document.id, Document.bot_id, Document.organization_id, Document.title,
        Document.filename, Document.canonical_url, Document.source_url,
        Document.source_type, Document.status, Document.metadata_json,
        Document.version, Document.updated_at, Document.content_hash, Document.crawl_id,
    )).order_by(Document.id).limit(limit).all()


def discover_documents(db, bot_id, organization_id, documents, terms, identity_score, limit=64, *, hard_scope=None):
    """Rank documents before chunk recall, including body-only topic evidence.

    Discovery alone may aggregate eligible corpus text in SQL. Return only
    IDs/scores, never global chunk bodies or vectors. Each term votes once per
    document, so long/repetitive pages cannot monopolize discovery. Exact active
    subjects bypass this query entirely.
    """
    body_scores = {}
    terms = list(dict.fromkeys(terms))[:8]
    if terms:
        matches = [Chunk.content.ilike("%" + term.replace("%", "\\%").replace("_", "\\_") + "%", escape="\\") for term in terms]
        score = sum(func.max(case((match, 1), else_=0)) for match in matches)
        rows = ready_chunks(
            db.query(Document.id, score.label("relevance")).join(Chunk, Chunk.document_id == Document.id),
            bot_id, organization_id, hard_scope=hard_scope,
        ).filter(or_(*matches)).group_by(Document.id).order_by(score.desc(), Document.id).limit(limit * 2).all()
        body_scores = dict(rows)
    ranked = sorted(documents, key=lambda doc: (
        -(2 * identity_score(doc) + body_scores.get(doc.id, 0)), doc.id,
    ))
    return [doc.id for doc in ranked[:limit]]
