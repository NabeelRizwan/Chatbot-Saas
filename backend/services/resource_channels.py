"""Bounded PostgreSQL candidate generation; hard predicates precede ranking.

Uses Phase 2's fixed expression/configuration and parameterized SQL conventions.
No text/embedding/factual metadata hydration, no normal DATABASE_URL use.
"""
from dataclasses import dataclass
from typing import Protocol
from sqlalchemy import and_, func, literal_column, or_, select
from database.models import Document
from database.resource_models import KnowledgeResource as Resource, KnowledgeResourceTerm as Term, KnowledgeResourceDocument as Link
from services.knowledge_scope import ready_documents

CHANNEL_LIMIT = 32
MAX_PROBES = 8
IDENTITY_KINDS = ("canonical", "alias", "title")


@dataclass(frozen=True)
class ProbeVariant:
    text: str
    provenance: str
    priority: int
    transformations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResourceProbe:
    text: str
    provenance: str = "explicit_user"
    original_span: str = ""
    probe_kind: str = "entity"
    explicit_resource_type_hint: str = ""
    inherited_resource_type_hint: str = ""
    comparison_group_id: str = ""
    comparison_member_index: int | None = None
    category_intent: bool = False
    relation_intent: str = ""
    reason_codes: tuple[str, ...] = ()
    variants: tuple[ProbeVariant, ...] = ()


@dataclass(frozen=True)
class CandidateSignal:
    resource_id: int
    channel: str
    rank: int
    raw_score: float
    term_id: int
    term_kind: str
    normalized_term: str
    term_source: str
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChannelBatch:
    signals: tuple[CandidateSignal, ...] = ()
    overflow: bool = False


class FeatureUnavailable(RuntimeError):
    pass


class ResourceCandidateChannel(Protocol):
    name: str
    def search(self, db, hard, probe: ResourceProbe, limit: int) -> ChannelBatch: ...


class OptionalDenseResourceChannel(Protocol):
    """Deferred interface. Caller must supply an already profile-safe vector.

    No default implementation, vector population, or model call is provided.
    A future implementation must use the same eligible-anchor query below.
    """
    name: str
    def search(self, db, hard, probe: ResourceProbe, limit: int) -> ChannelBatch: ...


def eligible_anchors(db, hard):
    docs = ready_documents(db, hard.bot_id, hard.organization_id, hard_scope=hard).with_entities(
        Document.id.label("document_id"), Document.version.label("version"), Document.crawl_id.label("crawl_id"))
    d = docs.subquery("resource_eligible_documents")
    return select(Link.resource_id, Link.document_id, d.c.version, d.c.crawl_id).join(d, and_(
        d.c.document_id == Link.document_id, d.c.version == Link.document_version,
        or_(d.c.crawl_id == Link.document_crawl_id, and_(d.c.crawl_id.is_(None), Link.document_crawl_id.is_(None))),
    )).where(Link.organization_id == hard.organization_id, Link.bot_id == hard.bot_id).cte("resource_anchors")


def term_statement(db, hard, score, *, anchors=None):
    anchors = eligible_anchors(db, hard) if anchors is None else anchors
    # EXISTS avoids multiplying a term by the number of supporting documents.
    anchored = select(1).select_from(anchors).where(anchors.c.resource_id == Resource.id).exists()
    origin = select(1).select_from(anchors).where(
        anchors.c.resource_id == Resource.id, anchors.c.document_id == Term.source_document_id,
        anchors.c.version == Term.source_version,
        or_(anchors.c.crawl_id == Term.source_crawl_id,
            and_(anchors.c.crawl_id.is_(None), Term.source_crawl_id.is_(None))),
    ).exists()
    return select(Resource.id.label("resource_id"), Term.id.label("term_id"), Term.term_kind,
                  Term.normalized_term, Term.term_source, score.label("score")).select_from(Term).join(
        Resource, and_(Resource.id == Term.resource_id, Resource.organization_id == Term.organization_id,
                       Resource.bot_id == Term.bot_id)).where(
        Resource.organization_id == hard.organization_id, Resource.bot_id == hard.bot_id, Resource.status == "ready",
        Term.organization_id == hard.organization_id, Term.bot_id == hard.bot_id, anchored,
        or_(and_(Term.source_document_id.is_(None), Term.term_source.in_(("admin", "explicit"))), origin))


def bounded_terms(statement, limit):
    if type(limit) is not int or not 1 <= limit <= CHANNEL_LIMIT:
        raise ValueError("Invalid resource candidate limit")
    rows = statement.subquery("resource_term_matches")
    best = select(rows, func.row_number().over(partition_by=rows.c.resource_id,
                  order_by=(rows.c.score.desc(), rows.c.term_id)).label("term_position")).subquery("resource_best_term")
    # +1 proves truncation; no arbitrary exact winner when collisions overflow.
    return select(best).where(best.c.term_position == 1).order_by(best.c.score.desc(), best.c.resource_id).limit(limit + 1)


class SQLResourceChannel:
    def __init__(self, name):
        if name not in {"exact", "fts", "trigram", "metadata"}:
            raise ValueError("Unknown resource channel")
        self.name = name

    def statement(self, db, hard, probe, limit):
        from services.resource_normalization import normalize_resource_text
        text = normalize_resource_text(probe.text)
        if self.name == "exact":
            return bounded_terms(term_statement(db, hard, literal_column("1.0")).where(
                Term.normalized_term == text, Term.term_kind.in_(IDENTITY_KINDS)), limit)
        if self.name == "metadata":
            # Exact navigation/type metadata is a weak route, not canonical proof.
            if probe.provenance == "category":
                # Generic English plural surface forms; no resource-type list.
                return bounded_terms(term_statement(db, hard, literal_column("1.0")).where(
                    Term.term_kind == "resource_type", or_(Term.normalized_term == text,
                        Term.normalized_term + "s" == text,
                        and_(Term.normalized_term.endswith("y"), func.substr(Term.normalized_term, 1, func.length(Term.normalized_term)-1) + "ies" == text))), limit)
            return bounded_terms(term_statement(db, hard, literal_column("1.0")).where(
                Term.normalized_term == text, Term.term_kind.in_(("url_slug", "breadcrumb", "resource_type", "heading"))), limit)
        if db.get_bind().dialect.name != "postgresql":
            raise FeatureUnavailable("PostgreSQL resource channel unavailable")
        if self.name == "fts":
            config = literal_column("'simple'::regconfig")
            vector = func.to_tsvector(config, Term.normalized_term)
            query = func.plainto_tsquery(config, text)
            return bounded_terms(term_statement(db, hard, func.ts_rank_cd(vector, query)).where(
                vector.op("@@")(query), Term.term_kind != "resource_type"), limit)
        # pg_trgm operators use the server's candidate-generation thresholds;
        # neither threshold nor nearest raw score can authorize resolution.
        score = func.greatest(func.similarity(Term.normalized_term, text),
                              func.strict_word_similarity(text, Term.normalized_term))
        return bounded_terms(term_statement(db, hard, score).where(
            or_(Term.normalized_term.op("%")(text), Term.normalized_term.op("%>>")(text)),
            Term.term_kind != "resource_type"), limit)

    def search(self, db, hard, probe, limit=CHANNEL_LIMIT):
        from services.resource_normalization import normalize_resource_text
        normalized = normalize_resource_text(probe.text)
        if not normalized or (self.name == "trigram" and (len(normalized) < 5 or max(map(len, normalized.split()), default=0) < 4)):
            return ChannelBatch()
        rows = db.execute(self.statement(db, hard, probe, limit)).all()
        return ChannelBatch(tuple(CandidateSignal(r.resource_id, self.name, rank, float(r.score), r.term_id,
                            r.term_kind, r.normalized_term, r.term_source) for rank, r in enumerate(rows[:limit], 1)),
                            len(rows) > limit)
