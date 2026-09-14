"""Transactional metadata projection; no crawl, content parsing or model calls.

Caller owns commit/rollback. Never accepts similarity as persistence identity.
Catalog revision changes are enforced by database triggers, including direct
SQL mutations; reading the revision does not mutate the database.
"""
import hashlib
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import load_only
from database.models import Bot, Document
from database.resource_models import (KnowledgeResource as Resource, KnowledgeResourceTerm as Term,
                                      KnowledgeResourceDocument as Link, ResourceCatalogState as State)
from services.knowledge_scope import ready_documents
from services.resource_normalization import normalize_resource_text


def catalog_revision(db, hard):
    return int(db.execute(select(State.revision).where(State.organization_id == hard.organization_id,
                           State.bot_id == hard.bot_id)).scalar_one_or_none() or 0)


def safe_navigation_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 for c in value):
        return None
    try:
        url = urlsplit(value)
        if url.scheme in {"http", "https"} and url.hostname and not url.username and not url.password:
            # Signed/token-bearing URLs aren't catalog navigation metadata.
            if not url.query and not url.fragment:
                return value
    except ValueError:
        pass
    return None


def projection(doc):
    metadata = doc.metadata_json if isinstance(doc.metadata_json, dict) else {}
    explicit = metadata.get("resource_id")
    key = "explicit:" + hashlib.sha256(str(explicit).encode()).hexdigest() if isinstance(explicit, (str, int)) and str(explicit) else f"document:{doc.id}"
    name = metadata.get("canonical_name") or doc.title or doc.filename
    if not isinstance(name, str) or not normalize_resource_text(name):
        raise ValueError("Source has no bounded resource name")
    kind = metadata.get("resource_type") or "document"
    if not isinstance(kind, str) or not 1 <= len(kind) <= 80:
        raise ValueError("Invalid resource type")
    url = safe_navigation_url(doc.canonical_url or doc.source_url)
    breadcrumb = metadata.get("breadcrumb", [])
    if isinstance(breadcrumb, str):
        breadcrumb = [breadcrumb]
    breadcrumb = [v for v in breadcrumb[:8] if isinstance(v, str) and len(v) <= 512] if isinstance(breadcrumb, list) else []
    terms = [(name, "canonical", "document_metadata")]
    if isinstance(doc.title, str) and doc.title:
        terms.append((doc.title, "title", "document_metadata"))
    aliases = metadata.get("aliases", [])
    if isinstance(aliases, str):
        aliases = [aliases]
    if isinstance(aliases, list):
        if len(aliases) > 32:
            raise ValueError("Source alias count exceeds projection bound")
        terms.extend((a, "alias", "explicit") for a in aliases if isinstance(a, str))
    if url:
        terms.append((unquote(urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]), "url_slug", "derived"))
    terms.extend((v, "breadcrumb", "document_metadata") for v in breadcrumb)
    terms.append((kind, "resource_type", "document_metadata"))
    normalized = sorted({(text, normalize_resource_text(text), term_kind, source)
                         for text, term_kind, source in terms if text and normalize_resource_text(text)})
    return key, dict(canonical_name=name, normalized_canonical_name=normalize_resource_text(name),
                     resource_type=kind, title=doc.title, url=url, breadcrumb=breadcrumb), normalized


@dataclass(frozen=True)
class ProjectionResult:
    examined: int
    changed: int
    revision: int
    dry_run: bool


class ResourceCatalogProjector:
    """Explicit bounded batch; no automatic customer backfill on chat/startup."""
    def project(self, db, hard, document_ids, *, dry_run=False):
        ids = tuple(sorted(set(document_ids)))
        if len(ids) > 256:
            raise ValueError("Project at most 256 source documents per transaction")
        if hard.empty or hard.intersect(ids) != ids:
            raise ValueError("Projection outside hard scope")
        # Serialize only this bot's projector, before reads; no global locks.
        if not dry_run:
            if db.execute(select(Bot.id).where(Bot.id == hard.bot_id, Bot.organization_id == hard.organization_id)
                          .with_for_update()).scalar_one_or_none() is None:
                raise ValueError("Projection owner unavailable")
        docs = ready_documents(db, hard.bot_id, hard.organization_id, hard_scope=hard).filter(Document.id.in_(ids)).options(
            load_only(Document.id, Document.title, Document.filename, Document.metadata_json,
                      Document.canonical_url, Document.source_url, Document.version, Document.crawl_id)).order_by(Document.id).all()
        prepared = [(d, *projection(d)) for d in docs]
        keys = [row[1] for row in prepared]
        resources = {r.source_key: r for r in db.query(Resource).filter(Resource.organization_id == hard.organization_id,
                     Resource.bot_id == hard.bot_id, Resource.source_key.in_(keys)).all()}
        terms = db.query(Term).filter(Term.organization_id == hard.organization_id, Term.bot_id == hard.bot_id,
                                     Term.source_document_id.in_(ids)).all()
        links = db.query(Link).filter(Link.organization_id == hard.organization_id, Link.bot_id == hard.bot_id,
                                     Link.document_id.in_(ids)).all()
        changed = 0
        for doc, key, attrs, wanted in prepared:
            resource = resources.get(key)
            prior_terms = [t for t in terms if t.source_document_id == doc.id]
            prior_links = [link for link in links if link.document_id == doc.id]
            content_changed = not resource or any(getattr(resource, k) != v for k, v in attrs.items())
            # An explicitly shared resource can have several source titles. The
            # first projection owns its display label; each source retains terms.
            if resource and key.startswith("explicit:") and resource.metadata_json.get("primary_document_id") != doc.id:
                content_changed = False
            current = sorted((t.term_text, t.normalized_term, t.term_kind, t.term_source) for t in prior_terms
                             if resource and t.resource_id == resource.id and t.source_version == doc.version
                             and t.source_crawl_id == doc.crawl_id)
            link_ok = len(prior_links) == 1 and resource and prior_links[0].resource_id == resource.id and prior_links[0].document_version == doc.version and prior_links[0].document_crawl_id == doc.crawl_id
            if not content_changed and current == wanted and len(current) == len(prior_terms) and link_ok:
                continue
            changed += 1
            if dry_run:
                continue
            if resource is None:
                resource = Resource(organization_id=hard.organization_id, bot_id=hard.bot_id, source_key=key,
                                    **attrs, metadata_json={"primary_document_id": doc.id}, status="ready", version=1)
                db.add(resource)
                db.flush()
                resources[key] = resource
            elif content_changed:
                for k, v in attrs.items():
                    setattr(resource, k, v)
                resource.version += 1
            for old in (*prior_terms, *prior_links):
                db.delete(old)
            db.flush()
            db.add(Link(organization_id=hard.organization_id, bot_id=hard.bot_id, resource_id=resource.id,
                        document_id=doc.id, document_version=doc.version, document_crawl_id=doc.crawl_id))
            for display, normalized, kind, source in wanted:
                db.add(Term(organization_id=hard.organization_id, bot_id=hard.bot_id, resource_id=resource.id,
                            term_text=display, normalized_term=normalized, term_kind=kind, term_source=source,
                            source_document_id=doc.id, source_version=doc.version, source_crawl_id=doc.crawl_id))
        if not dry_run:
            db.flush()
        return ProjectionResult(len(ids), changed, catalog_revision(db, hard), dry_run)
