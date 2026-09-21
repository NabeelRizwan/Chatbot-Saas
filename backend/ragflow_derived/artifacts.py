"""Owned, immutable compiled-artifact publication around the upstream DocStore.

This is a storage/authorization adapter, not a search algorithm. Searches use
the existing ElasticsearchQuery unchanged. A compilation writes a private index
and publishes a manifest only after every row has exact leaf-source lineage.
Generated artifacts never enter the ordinary source index.
"""
import asyncio
import copy
import hashlib
import json
import re
import threading
from dataclasses import dataclass
from uuid import uuid4
from .contracts import EngineError
from .upstream.doc_store import OrderByExpr


MAX_ARTIFACT_ROWS = 10000


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def inventory(scope):
    return digest([scope.key, sorted(s.key for s in scope.sources)])


@dataclass(frozen=True)
class ArtifactIndex:
    key: str
    index: str
    dimension: int


class ElasticsearchArtifactIO:
    """Explicit-client IO. No settings, credentials, or implicit connection discovery."""
    def __init__(self, backend):
        self.backend, self.client = backend, backend.client

    def create(self, index):
        self.backend.create(index)

    def insert(self, index, rows):
        operations = []
        for row in rows:
            operations.extend([{'index': {'_index': index.index, '_id': row['id']}}, row])
        if operations and self.client.bulk(operations=operations, refresh='wait_for').get('errors'):
            raise EngineError('INDEX_FAILED', 'compiled bulk')

    def delete_rows(self, index, ids):
        if not ids:
            return
        result = self.client.delete_by_query(index=index.index, refresh=True,
                                             query={'ids': {'values': ids}})
        if result.get('timed_out') or result.get('failures') or result.get('version_conflicts'):
            raise EngineError('INDEX_FAILED', 'compiled deletion')

    def search(self, *args, **kwargs):
        return self.backend.search(*args, **kwargs)

    def publish(self, scope, key, manifest):
        from elasticsearch import ConflictError
        try:
            # CREATE is an atomic publish-once CAS. Racing compilers cannot
            # replace a completed generation or overwrite another publisher.
            # The pinned *_with_weight mapping stores unindexed text. Never
            # dynamically map thousands of chunk IDs as object field names.
            document = {'scope_key_kwd': scope.key, 'available_int': 0,
                        'compiled_manifest_with_weight': json.dumps(manifest, sort_keys=True,
                            ensure_ascii=False, allow_nan=False)}
            self.client.create(index=scope.index, id=key, document=document, refresh='wait_for')
        except ConflictError:
            raise EngineError('INDEX_FAILED', 'compiled generation already published') from None

    def load(self, scope, key):
        from elasticsearch import NotFoundError
        try:
            row = self.client.get(index=scope.index, id=key)['_source']
            if row.get('scope_key_kwd') != scope.key or row.get('available_int') != 0:
                raise EngineError('PROVENANCE_FAILED', 'compiled manifest envelope')
            return json.loads(row['compiled_manifest_with_weight'])
        except NotFoundError:
            return None

    def abandon(self, index):
        # Caller owns this unique, unpublished index, not the source index.
        if not re.fullmatch(r'rfcompiled_[a-f0-9]{64}_[a-f0-9]{32}', index.index):
            raise EngineError('UNAUTHORIZED_SCOPE', 'compiled cleanup target')
        self.client.indices.delete(index=index.index)


class PrivateCompileLock:
    """Per-private-index lock; no shared mutable dataset is compiled in place."""
    def __init__(self, lock):
        self.lock = lock

    async def spin_acquire(self):
        while not self.acquire():
            await asyncio.sleep(0.01)
        return True

    def acquire(self):
        return self.lock.acquire(blocking=False)

    def release(self):
        self.lock.release()


class ArtifactSession:
    def __init__(self, source_store, io, kind, *, manifest=None):
        if kind not in {'raptor', 'structure', 'graph'}:
            raise EngineError('MODE_UNAVAILABLE', 'artifact kind')
        self.source_store, self.scope, self.io, self.kind = source_store, source_store.scope, io, kind
        self.owner = inventory(self.scope)
        self.manifest_key = 'compiled_' + digest([self.owner, kind])
        self.writable = manifest is None
        self.published = False
        self.publish_attempted = False
        self.rows, self.leaves, self.seen = {}, {}, {}
        self.derived_lineage = {}
        self.locks = {}
        self.check()
        if manifest is None:
            self.index = ArtifactIndex(self.scope.key, 'rfcompiled_' + self.owner + '_' + uuid4().hex,
                                       self.scope.dimension)
            self.io.create(self.index)
        else:
            self._validate_manifest(manifest)
            self.index = ArtifactIndex(self.scope.key, manifest['index'], self.scope.dimension)
            self.rows = copy.deepcopy(manifest['rows'])
            self.leaves = copy.deepcopy(manifest['leaves'])
            self.published = True

    @classmethod
    def open(cls, source_store, io, kind):
        key = 'compiled_' + digest([inventory(source_store.scope), kind])
        manifest = io.load(source_store.scope, key)
        if manifest is None:
            raise EngineError('MODE_UNAVAILABLE', 'compiled artifacts not published')
        return cls(source_store, io, kind, manifest=manifest)

    def _fail(self, code='UNAUTHORIZED_SCOPE', stage='compiled artifact'):
        op = self.source_store.operation
        if op:
            op.refuse(code, stage)
        raise EngineError(code, stage)

    def check(self):
        self.source_store.check()
        # A compiled aggregate can mention every source used to create it. No
        # stale/deleted source in its immutable inventory may remain available.
        if self.source_store.backend.ready_sources(self.scope) != {s.key for s in self.scope.sources}:
            self._fail(stage='compiled source readiness')

    def _validate_manifest(self, manifest):
        if (not isinstance(manifest, dict) or manifest.get('owner') != self.owner
                or manifest.get('scope_key_kwd') != self.scope.key or manifest.get('kind') != self.kind
                or manifest.get('available_int') != 0 or not isinstance(manifest.get('rows'), dict)
                or not isinstance(manifest.get('leaves'), dict)
                or not 0 < len(manifest['rows']) <= MAX_ARTIFACT_ROWS
                or len(manifest['leaves']) > MAX_ARTIFACT_ROWS
                or not re.fullmatch('rfcompiled_' + self.owner + '_[a-f0-9]{32}', str(manifest.get('index', '')))
                or manifest.get('seal') != digest({k: v for k, v in manifest.items() if k != 'seal'})):
            self._fail('PROVENANCE_FAILED', 'compiled manifest')

    def add_leaves(self, rows):
        if not self.writable:
            self._fail(stage='read-only compilation')
        for row in rows:
            self.source_store.validate_row(row)
            self.leaves[row['id']] = {'source_key': row['source_version_kwd'], 'doc': row['doc_id'],
                                      'sha': row['content_sha_kwd']}
        if len(self.leaves) > MAX_ARTIFACT_ROWS:
            self._fail('INGESTION_FAILED', 'compiled source bound')

    def lock_factory(self, scope, key, **kwargs):
        if not self.writable or scope != self.scope:
            self._fail(stage='compilation lock authority')
        return PrivateCompileLock(self.locks.setdefault(str(key), threading.Lock()))

    def register_tree_lineage(self, doc_id, graph):
        """Resolve parent lineage from actual upstream child edges, as sidecar
        metadata only. Do not add source pointers to the model-facing graph."""
        nodes = {n['name']: n for n in graph['entities']}
        if len(nodes) != len(graph['entities']) or len(nodes) > MAX_ARTIFACT_ROWS:
            self._fail('PROVENANCE_FAILED', 'tree node identity')
        children = {name: [] for name in nodes}
        for edge in graph['relations']:
            if edge.get('type') != 'child' or edge['from'] not in nodes or edge['to'] not in nodes:
                self._fail('PROVENANCE_FAILED', 'tree edge')
            children[edge['from']].append(edge['to'])
        memo, visiting = {}, set()
        def resolve(name):
            if name in memo:
                return memo[name]
            if name in visiting or len(visiting) > 256:
                self._fail('PROVENANCE_FAILED', 'tree cycle/depth')
            visiting.add(name)
            leaves = set(nodes[name].get('source_chunk_ids', []))
            for child in children[name]:
                leaves.update(resolve(child))
            if not leaves or not leaves.issubset(self.leaves):
                self._fail('PROVENANCE_FAILED', 'tree source linkage')
            if any(self.leaves[cid]['doc'] != doc_id for cid in leaves):
                self._fail(stage='tree source document')
            visiting.remove(name)
            memo[name] = sorted(leaves)
            return memo[name]
        for name in nodes:
            self.derived_lineage[(doc_id, 'tree', name)] = resolve(name)

    def _lineage(self, row, nodes=None):
        if self.kind == 'graph':
            # Pinned GraphRAG deliberately stores document-level source_id,
            # not the extractor's transient chunk IDs. Preserve that precision:
            # sidecar leaves are document support, not exact claim attribution.
            docs = row.get('source_id')
            allowed = {v['doc'] for v in self.leaves.values()}
            if not isinstance(docs, list) or not docs or not set(docs).issubset(allowed):
                self._fail(stage='KG document lineage')
            if row.get('knowledge_graph_kwd') in {'graph', 'subgraph'}:
                graph = json.loads(row['content_with_weight'])
                parts = [graph.get('graph', {})] + graph.get('nodes', []) + graph.get('edges', [])
                for part in parts:
                    pointers = part.get('source_id', [])
                    if not isinstance(pointers, list) or not set(pointers).issubset(allowed):
                        self._fail(stage='KG embedded document lineage')
                # Subgraphs may retain edge provenance from merged documents.
                # Include every embedded pointer, never narrow it to the row label.
                docs = list(set(docs) | {d for part in parts for d in part.get('source_id', [])})
            return sorted(k for k, v in self.leaves.items() if v['doc'] in docs)
        ids = row.get('source_chunk_ids') or []
        if isinstance(ids, str):
            ids = [ids]
        if not ids and row.get('knowledge_graph_kwd') == 'entity':
            payload = json.loads(row['content_with_weight'])
            ids = self.derived_lineage.get((row.get('doc_id'), row.get('compile_kwd'), payload.get('name')), [])
        if row.get('compile_kwd') == 'dataset_nav':
            # Upstream nav rows carry document membership, not leaf IDs. Expand
            # their exact document membership using this sealed build inventory.
            docs = row.get('doc_ids_kwd') or [row.get('doc_id')]
            if not set(docs).issubset({v['doc'] for v in self.leaves.values()}):
                self._fail(stage='navigation document lineage')
            ids = [k for k, v in self.leaves.items() if v['doc'] in docs]
        if not ids and row.get('knowledge_graph_kwd') == 'graph':
            graph = json.loads(row['content_with_weight'])
            entities = graph.get('entities') or []
            names = {str(e.get('name') or e.get('id')) for e in entities}
            if any(str(r.get(k)) not in names for r in graph.get('relations', []) for k in ('from', 'to')):
                self._fail('PROVENANCE_FAILED', 'graph endpoint lineage')
            ids = [cid for e in entities for cid in e.get('source_chunk_ids', [])]
        if not ids and row.get('knowledge_graph_kwd') == 'relation':
            key = (row.get('doc_id'), row.get('compile_kwd'))
            ends = [row.get('from_entity_kwd'), row.get('to_entity_kwd')]
            if not nodes or any((*key, end) not in nodes for end in ends):
                self._fail('PROVENANCE_FAILED', 'relation endpoint lineage')
            ids = [cid for end in ends for cid in nodes[(*key, end)]]
        if not ids or not set(ids).issubset(self.leaves):
            self._fail('PROVENANCE_FAILED', 'generated leaf lineage')
        return sorted(set(ids))

    def insert(self, rows):
        self.check()
        if not self.writable:
            self._fail(stage='read-only artifact operation')
        prepared = []
        nodes = {tuple(v['node']): v['leaves'] for v in self.rows.values() if v.get('node')}
        for row in rows:
            if row.get('knowledge_graph_kwd') == 'entity':
                payload = json.loads(row['content_with_weight'])
                name = str(payload.get('name') or payload.get('id') or row.get('entity_kwd') or '')
                nodes[(row.get('doc_id'), row.get('compile_kwd'), name)] = self._lineage(row)
        for item in rows:
            row = copy.deepcopy(item)
            # DocStore accepts NumPy vectors; JSON transport materializes the
            # identical numeric sequence without re-encoding or normalization.
            for key, value in list(row.items()):
                if key.startswith('q_') and key.endswith('_vec') and hasattr(value, 'tolist'):
                    row[key] = value.tolist()
            row.pop('_score', None)  # search transport metadata, not stored data
            cid = row.get('id')
            if not isinstance(cid, str) or not cid or len(cid) > 256:
                self._fail('PROVENANCE_FAILED', 'generated identity')
            lineage = self._lineage(row, nodes)
            if not isinstance(row.get('content_with_weight'), str):
                self._fail('PROVENANCE_FAILED', 'generated payload')
            row.update(scope_key_kwd=self.scope.key, kb_id=self.scope.bot_id,
                       generation_kwd=self.scope.generation, artifact_owner_kwd=self.owner,
                       generated_int=1, artifact_leaf_ids=lineage)
            row.setdefault('available_int', 1)
            row['artifact_hash_kwd'] = digest({k: v for k, v in row.items() if k != 'artifact_hash_kwd'})
            prepared.append(row)
        if len(set(self.rows) | {r['id'] for r in prepared}) > MAX_ARTIFACT_ROWS:
            self._fail('INGESTION_FAILED', 'compiled row bound')
        self.io.insert(self.index, prepared)
        for row in prepared:
            self.rows[row['id']] = {'sha': row['artifact_hash_kwd'], 'leaves': row['artifact_leaf_ids']}
            if row.get('knowledge_graph_kwd') == 'entity':
                payload = json.loads(row['content_with_weight'])
                name = str(payload.get('name') or payload.get('id') or row.get('entity_kwd') or '')
                self.rows[row['id']]['node'] = [row.get('doc_id'), row.get('compile_kwd'), name]

    def validate(self, row, cid):
        expected = self.rows.get(cid)
        if (not expected or row.get('id') != cid or row.get('scope_key_kwd') != self.scope.key
                or row.get('kb_id') != self.scope.bot_id or row.get('artifact_owner_kwd') != self.owner
                or row.get('generation_kwd') != self.scope.generation or row.get('generated_int') != 1
                or row.get('artifact_leaf_ids') != expected['leaves']
                or row.get('artifact_hash_kwd') != expected['sha']
                or digest({k: v for k, v in row.items() if k != 'artifact_hash_kwd'}) != expected['sha']):
            self._fail('PROVENANCE_FAILED', 'returned compiled row')
        self._validate_leaves(expected['leaves'])

    def _validate_leaves(self, ids):
        ids = sorted(set(ids))
        if not ids or not set(ids).issubset(self.leaves):
            self._fail('PROVENANCE_FAILED', 'returned leaf pointers')
        result = self.source_store.search(['id'], [], {'id': ids}, [], OrderByExpr(), 0, len(ids),
                                          [self.scope.index], [self.scope.bot_id])
        rows = result['hits']['hits']
        if {h['_id'] for h in rows} != set(ids):
            self._fail('PROVENANCE_FAILED', 'missing original supporting leaf')
        for hit in rows:
            expected = self.leaves[hit['_id']]
            row = hit['_source']
            if (row['content_sha_kwd'] != expected['sha'] or row['source_version_kwd'] != expected['source_key']
                    or row['doc_id'] != expected['doc']):
                self._fail('PROVENANCE_FAILED', 'changed original supporting leaf')

    def eligible(self, documents=None):
        allowed = {s.document_id for s in self.scope.sources}
        if self.source_store.document_ids is not None:
            allowed &= self.source_store.document_ids
        if documents is not None:
            documents = [documents] if isinstance(documents, str) else documents
            if not set(documents).issubset(allowed):
                self._fail(stage='compiled document filter')
            allowed &= set(documents)
        return [cid for cid, row in self.rows.items()
                if row['leaves'] and all(self.leaves[leaf]['doc'] in allowed for leaf in row['leaves'])]

    def search(self, fields, highlights, condition, expressions, order, offset, limit, **kwargs):
        self.check()
        condition = copy.deepcopy(condition)
        eligible = set(self.eligible(condition.get('doc_id')))
        requested_ids = condition.get('id')
        if requested_ids is not None:
            requested_ids = [requested_ids] if isinstance(requested_ids, str) else requested_ids
            if not self.writable and not set(requested_ids).issubset(eligible):
                self._fail(stage='model compiled node ID')
            eligible &= set(requested_ids)
        if not eligible:
            return {'hits': {'total': {'value': 0}, 'hits': []}}
        condition.update(id=sorted(eligible), scope_key_kwd=self.scope.key, artifact_owner_kwd=self.owner,
                         generation_kwd=self.scope.generation, generated_int=1)
        # Full payload is required for hash/lineage verification before projection.
        result = self.io.search([], highlights, condition, expressions, order, offset, limit,
                                [self.index.index], [self.scope.bot_id], **kwargs)
        self.check()
        for hit in result['hits']['hits']:
            if hit['_id'] not in eligible:
                self._fail(stage='compiled candidate filter')
            self.validate(hit['_source'], hit['_id'])
            self.seen[hit['_id']] = copy.deepcopy(hit['_source'])
        return result

    def delete(self, condition):
        if not self.writable:
            self._fail(stage='read-only artifact deletion')
        hits = self.search([], [], condition, [], OrderByExpr(), 0, MAX_ARTIFACT_ROWS)['hits']['hits']
        ids = [h['_id'] for h in hits]
        self.io.delete_rows(self.index, ids)
        for cid in ids:
            self.rows.pop(cid, None)
        return len(ids)

    def search_raptor(self, fields, highlights, condition, expressions, order, offset, limit, **kwargs):
        """One upstream ES query over source leaves + summary rows, as upstream
        RAPTOR does. Index separation is storage-only, never two rankings fused
        by a custom algorithm. Authorization IDs constrain both physical indices."""
        self.check()
        condition = copy.deepcopy(condition)
        docs = {s.document_id for s in self.scope.sources}
        if self.source_store.document_ids is not None:
            docs &= self.source_store.document_ids
        if condition.get('doc_id') is not None:
            requested = condition['doc_id']
            requested = [requested] if isinstance(requested, str) else requested
            if not set(requested).issubset(docs):
                self._fail(stage='RAPTOR document filter')
            docs &= set(requested)
        eligible = set(self.eligible(sorted(docs))) | {cid for cid, leaf in self.leaves.items() if leaf['doc'] in docs}
        if condition.get('id') is not None:
            requested = condition['id']
            requested = [requested] if isinstance(requested, str) else requested
            if not set(requested).issubset(eligible):
                self._fail(stage='RAPTOR candidate ID')
            eligible &= set(requested)
        if not eligible:
            return {'hits': {'total': {'value': 0}, 'hits': []}}
        condition.update(id=sorted(eligible), scope_key_kwd=self.scope.key,
                         generation_kwd=self.scope.generation, available_int=1)
        result = self.io.search([], highlights, condition, expressions, order, offset, limit,
                                [self.scope.index, self.index.index], [self.scope.bot_id], **kwargs)
        self.check()
        for hit in result['hits']['hits']:
            cid, row = hit['_id'], hit['_source']
            if cid not in eligible:
                self._fail(stage='RAPTOR candidate membership')
            if cid in self.rows:
                self.validate(row, cid)
                self.seen[cid] = copy.deepcopy(row)
            else:
                self.source_store.validate_row(row)
                expected = self.leaves[cid]
                if row['content_sha_kwd'] != expected['sha'] or row['source_version_kwd'] != expected['source_key']:
                    self._fail('PROVENANCE_FAILED', 'RAPTOR original leaf')
                self.source_store.seen[cid] = copy.deepcopy(row)
        return result

    def update(self, condition, values):
        if not self.writable:
            self._fail(stage='read-only artifact update')
        hits = self.search([], [], condition, [], OrderByExpr(), 0, MAX_ARTIFACT_ROWS)['hits']['hits']
        immutable = {'id', 'scope_key_kwd', 'artifact_owner_kwd', 'generation_kwd', 'kb_id'}
        if any(values[k] != hit['_source'].get(k) for hit in hits for k in immutable & set(values)):
            self._fail(stage='compiled ownership update')
        rows = [dict(hit['_source'], **copy.deepcopy(values)) for hit in hits]
        self.insert(rows)
        return len(rows)

    def publish(self):
        self.check()
        if not self.writable or not self.rows:
            self._fail('INGESTION_FAILED', 'empty or read-only publication')
        self._validate_leaves(list(self.leaves))
        observed = self.search([], [], {}, [], OrderByExpr(), 0, MAX_ARTIFACT_ROWS)
        if (observed['hits']['total']['value'] != len(self.rows)
                or {h['_id'] for h in observed['hits']['hits']} != set(self.rows)):
            self._fail('PROVENANCE_FAILED', 'compiled readback inventory')
        manifest = {'scope_key_kwd': self.scope.key, 'owner': self.owner, 'index': self.index.index,
                    'kind': self.kind, 'available_int': 0, 'rows': copy.deepcopy(self.rows),
                    'leaves': copy.deepcopy(self.leaves)}
        manifest['seal'] = digest(manifest)
        self.publish_attempted = True
        self.io.publish(self.scope, self.manifest_key, manifest)
        self.published, self.writable = True, False
        return manifest['seal']

    def abandon(self):
        if self.writable and not self.published:
            if self.publish_attempted:
                # A timed-out CREATE may have succeeded. Never delete an index
                # referenced by a visible publication, or guess on failed readback.
                manifest = self.io.load(self.scope, self.manifest_key)
                if manifest and manifest.get('index') == self.index.index:
                    self.published, self.writable = True, False
                    return
            self.io.abandon(self.index)
            self.writable = False
