"""Bind every evidence span to the currently authorized SaaS document version."""
import hashlib
import json
import math
from types import SimpleNamespace

from database.models import Bot
from services.native_rag.knowledge import ready_documents
from services.structural_chunking import count_tokens
from .client import RetrievalClient, RetrievalError
from .subjects import linked_subjects


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


class KnowledgeScope:
    def __init__(self, db, bot, client=None):
        self.db = db
        self.bot_id, self.organization_id = bot.id, bot.organization_id
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
                        "fingerprint": fingerprint(self.records)}

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

    def retrieve(self, question):
        self.check()
        if not self.records:
            return [], '', {}
        result = self.client.retrieve(self.payload, self.records, question)
        self.check()
        if result.get('fingerprint') != self.payload['fingerprint'] or result.get('question') != question:
            raise RetrievalError('retrieval_scope_mismatch')
        evidence = result.get('evidence')
        if not isinstance(evidence, list) or len(evidence) > 64:
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
                          'match_reasons': ['LlamaIndex hybrid search + MiniLM + source context']})
        context = render_context(evidence)
        if context != result.get('context') or hashlib.sha256(context.encode()).hexdigest() != result.get('context_sha256'):
            raise RetrievalError('evidence_context_integrity_failed')
        if count_tokens(context) > 4000:
            raise RetrievalError('evidence_context_budget_exceeded')
        return items, context, result
