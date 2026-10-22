"""Bind every evidence span to the currently authorized SaaS document version."""
import hashlib
import json
import math
from types import SimpleNamespace

from database.models import Bot
from services.native_rag.knowledge import ready_documents
from services.structural_chunking import count_tokens
from .client import RetrievalClient, RetrievalError
from services.llama_rag.subjects import linked_subjects


def document_record(document, *, text=None, title=None, version=None, crawl_id=None, source_url=None):
    return {"id": str(document.id), "source_id": str(document.id),
        "title": title or document.title or document.filename,
        "url": source_url or document.canonical_url or document.source_url or f"document://{document.id}",
        "text": document.raw_text if text is None else text,
        "version": document.version if version is None else version,
        "crawl_id": document.crawl_id if version is None else crawl_id}


def fingerprint(records):
    return hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def render_context(evidence):
    blocks = []
    for item in evidence:
        subject = f"Subject: {item['subject_title']}\n" if item['subject_source_id'] != item['source_id'] else ""
        roles = ', '.join(item['evidence_roles'])
        role = f"Structural evidence roles: {roles}\n" if roles else ''
        headers = ''.join(f"Table header (source characters {header['start_char']}–{header['end_char']}):\n{header['text'].rstrip()}\n"
            for header in item['table_headers'] if header['included_in_context'])
        blocks.append(f"[Source {item['citation_id']}] {item['title']}\n{subject}Section: {item['section']}\n{role}URL: {item['url']}\n{headers}{item['text']}")
    return '\n\n'.join(blocks)


def _validate_role_spans(item):
    """Validate optional structural provenance without treating roles as truth."""
    spans = item.get('evidence_role_spans', [])
    if not isinstance(spans, list):
        raise RetrievalError('evidence_role_integrity_failed')
    for span in spans:
        if not isinstance(span, dict):
            raise RetrievalError('evidence_role_integrity_failed')
        start, end = span.get('start_char'), span.get('end_char')
        role = span.get('evidence_role')
        if (type(start) is not int or type(end) is not int
                or not item['start_char'] <= start < end <= item['end_char']
                or not isinstance(role, str) or role not in {'PRIMARY', 'FAQ', 'POLICY', 'REVIEW', 'UNKNOWN'}
                or role not in item.get('evidence_roles', [])
                or not isinstance(span.get('node_id'), str) or not span['node_id']
                or span['node_id'] not in [*item.get('core_node_ids', []), *item.get('expanded_node_ids', [])]
                or not isinstance(span.get('evidence_role_basis'), str)):
            raise RetrievalError('evidence_role_integrity_failed')


class KnowledgeScope:
    def __init__(self, db, bot, client=None):
        self.db = db
        self.bot_id, self.organization_id = bot.id, bot.organization_id
        from services.knowledge_policy import current_pipeline_policy
        accepted = current_pipeline_policy()
        if accepted is not None and (accepted.organization_id != self.organization_id
                                     or accepted.pipeline != 'rag2_improved'):
            raise RetrievalError('knowledge_pipeline_scope_mismatch')
        self.client = client or RetrievalClient()
        documents = ready_documents(db, bot).populate_existing().order_by('id').all()
        if len(documents) > 10000:
            raise RetrievalError("source_inventory_too_large")
        self.documents = {str(document.id): SimpleNamespace(**{key: getattr(document, key) for key in (
            'id', 'organization_id', 'bot_id', 'website_id', 'crawl_id', 'version', 'raw_text',
            'filename', 'title', 'source_type', 'source_url', 'canonical_url', 'content_hash', 'metadata_json')})
            for document in documents}
        self.records = self._records(documents)
        self.payload = {"organization_id": self.organization_id, "bot_id": self.bot_id,
                        "fingerprint": fingerprint(self.records),
                        "pipeline": "rag2_improved", "pipeline_build_revision": "rag2-voyage-v1"}

    @staticmethod
    def _records(documents):
        records = []
        for document in documents:
            if not document.raw_text or hashlib.sha256(document.raw_text.encode('utf-8')).hexdigest() != document.content_hash:
                raise RetrievalError("source_integrity_failed")
            records.append(document_record(document))
        return records

    def check(self):
        self.db.rollback()
        bot = self.db.query(Bot).filter(Bot.id == self.bot_id, Bot.organization_id == self.organization_id).one_or_none()
        if bot is None:
            raise RetrievalError("knowledge_authority_changed")
        current = self._records(ready_documents(self.db, bot).populate_existing().order_by('id').all())
        if fingerprint(current) != self.payload['fingerprint']:
            raise RetrievalError("knowledge_authority_changed")

    def retrieve(self, question, *, queries=None):
        self.check()
        if not self.records:
            return [], '', {}
        if queries is None:
            result = self.client.retrieve(self.payload, self.records, question)
        else:
            from .planned_client import retrieve_planned
            result = retrieve_planned(self.client, self.payload, self.records, question, queries)
        self.check()
        if result.get('fingerprint') != self.payload['fingerprint'] or result.get('question') != question:
            raise RetrievalError('retrieval_scope_mismatch')
        if (result.get('pipeline') != self.payload['pipeline']
                or result.get('pipeline_build_revision') != self.payload['pipeline_build_revision']):
            raise RetrievalError('retrieval_pipeline_mismatch')
        evidence = result.get('evidence')
        if not isinstance(evidence, list) or len(evidence) > (448 if queries is not None else 64):
            raise RetrievalError('evidence_inventory_invalid')
        by_id = {record['source_id']: record for record in self.records}
        items, seen, linked = [], set(), {}
        for index, item in enumerate(evidence):
            source = by_id.get(item.get('source_id'))
            subject = by_id.get(item.get('subject_source_id'))
            if source is None or item.get('citation_id') != str(index + 1):
                raise RetrievalError('evidence_source_invalid')
            if subject is None:
                key = source['source_id']
                if key not in linked:
                    linked[key] = linked_subjects(source, self.records)
                if (item.get('subject_source_id'), item.get('subject_title')) not in linked[key]:
                    raise RetrievalError('evidence_subject_invalid')
                subject = {'title': item['subject_title']}
            start, end = item.get('start_char'), item.get('end_char')
            if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source['text'])
                or item.get('text') != source['text'][start:end] or item.get('url') != source['url']
                or item.get('title') != source['title'] or item.get('subject_title') != subject['title']
                or item.get('source_sha256') != hashlib.sha256(source['text'].encode()).hexdigest()
                or not isinstance(item.get('node_id'), str) or not item['node_id'].startswith('context-')
                or item['node_id'] in seen or not math.isfinite(float(item.get('score', float('nan'))))):
                raise RetrievalError('evidence_integrity_failed')
            seen.add(item['node_id'])
            _validate_role_spans(item)
            for header in item.get('table_headers', []):
                a, b = header.get('start_char'), header.get('end_char')
                if (type(a) is not int or type(b) is not int or not 0 <= a < b <= len(source['text'])
                    or header.get('text') != source['text'][a:b] or header.get('source_id') != source['source_id']
                    or header.get('url') != source['url']):
                    raise RetrievalError('evidence_table_integrity_failed')
            document = self.documents[source['source_id']]
            chunk = SimpleNamespace(id='llama:' + item['node_id'], document_id=document.id,
                chunk_index=index, content=item['text'], token_count=count_tokens(item['text']),
                metadata_json={key: value for key, value in item.items() if key not in {'text', 'score'}},
                content_hash=hashlib.sha256(item['text'].encode()).hexdigest())
            items.append({'document': document, 'chunk': chunk, 'score': float(item['score']),
                          'match_reasons': ['RAG2 hybrid search + Voyage + source context'
                              if queries is not None else 'LlamaIndex hybrid search + MiniLM + source context'],
                          # The existing link validator admits references only
                          # from text actually supplied to the answer model.
                          'context_field_evidence': {'source_references': [item['text']]}})
        context = render_context(evidence)
        if context != result.get('context') or hashlib.sha256(context.encode()).hexdigest() != result.get('context_sha256'):
            raise RetrievalError('evidence_context_integrity_failed')
        if count_tokens(context) > (48000 if queries is not None else 4000):
            raise RetrievalError('evidence_context_budget_exceeded')
        return items, context, result


def answer_question(**kwargs):
    from .answer import answer_question as answer
    return answer(**kwargs)


def prepare(db, document, *, text, title, version, crawl_id, staging_id,
            check_cancelled=lambda: None, source_path=None, source_url=None):
    from services.llama_rag.ingestion import PROFILE
    check_cancelled()
    record = document_record(document, text=text, title=title, version=version,
                             crawl_id=crawl_id, source_url=source_url)
    result = RetrievalClient().request('/v1/prepare', record)
    check_cancelled()
    count = result.get('chunks')
    if type(count) is not int or not 0 < count <= 100000 or result.get('embeddings') != 0:
        raise RetrievalError('source_preparation_invalid')
    return SimpleNamespace(specs=range(count), metadata={**PROFILE, 'pipeline': 'rag2_improved'}, embeddings=0)


def promote(db, document, staging_id):
    # Both pipelines index the same atomically promoted canonical Documents.
    return None


def readiness():
    try:
        return RetrievalClient().readiness()
    except Exception:
        return 'unavailable'


def warm(db, bot):
    scope = KnowledgeScope(db, bot)
    if scope.records:
        scope.client.snapshot(scope.payload, scope.records)
        scope.check()


def prepare_corpus(db, bot, replacements, *, replaced_website_id=None):
    replaced_ids = {record['id'] for record in replacements}
    existing = [document for document in ready_documents(db, bot)
        if str(document.id) not in replaced_ids and
        (replaced_website_id is None or document.website_id != replaced_website_id)]
    records = sorted([*KnowledgeScope._records(existing), *replacements], key=lambda record: int(record['id']))
    payload = {'organization_id': bot.organization_id, 'bot_id': bot.id,
               'fingerprint': fingerprint(records), 'pipeline': 'rag2_improved',
               'pipeline_build_revision': 'rag2-voyage-v1'}
    db.rollback()
    RetrievalClient().snapshot(payload, records)
