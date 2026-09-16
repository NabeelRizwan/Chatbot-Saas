"""Transaction-owned, scoped structural storage. Not wired into ingestion/chat.

Management/staging APIs require trusted server-owned StorageScope. They are not
end-user authorization APIs. Serving reads additionally use HardKnowledgeScope
through the existing knowledge_scope predicates. Relationships grant no access.
OSS pattern provenance: docs/PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md.
"""
from dataclasses import dataclass
from hashlib import sha256
import json

from sqlalchemy import text, table, column, select, literal_column, and_

from services.structural_document import (
    ByteRange, ChunkStructuralMapping, NodeIdentity, RevisionIdentity, SourceIdentity,
    StructuralDocument, StructuralEdge, StructuralNode, StructureRevisionDescriptor, RevisionState,
)


class StructuralConflict(ValueError):
    pass


class StructuralScopeError(ValueError):
    pass


@dataclass(frozen=True)
class StorageScope:
    organization_id: int
    bot_id: int
    document_ids: frozenset[int]

    def __post_init__(self):
        if (type(self.organization_id) is not int or self.organization_id <= 0 or
                type(self.bot_id) is not int or self.bot_id <= 0 or
                not isinstance(self.document_ids, frozenset) or not self.document_ids or
                len(self.document_ids) > 10000 or any(type(i) is not int or i <= 0 for i in self.document_ids)):
            raise StructuralScopeError("explicit bounded server-owned document scope required")


@dataclass(frozen=True)
class RevisionCounts:
    nodes: int
    edges: int
    mappings: int

    def __post_init__(self):
        if any(type(v) is not int for v in (self.nodes,self.edges,self.mappings)) or not (
                1 <= self.nodes <= 10000 and 0 <= self.edges <= 20000 and 0 <= self.mappings <= 100000):
            raise ValueError("structural counts outside admission bounds")


OWNER = "organization_id=:org AND bot_id=:bot AND document_id=:doc"
REVISION = OWNER + " AND structure_revision_id=:rev"
JSON_FIELDS = {"quality", "attributes", "provenance"}
SOURCE_COLUMNS = ("organization_id", "bot_id", "document_id", "id", "source_version", "source_sha256")


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _bound(limit, maximum=256):
    if type(limit) is not int or not 1 <= limit <= maximum:
        raise ValueError("explicit read/batch limit outside bounds")
    return limit


def _validate(value, cls):
    if not isinstance(value, cls):
        raise ValueError("typed structural DTO required")
    return cls.model_validate_json(value.canonical_json())


def logical_edge_key(edge):
    """Endpoints/kind/evidence identify an edge; confidence is not a new edge."""
    payload = edge.model_dump(mode="json")
    payload.pop("validation_state")
    payload["provenance"].pop("confidence")
    return sha256(_json(payload).encode()).hexdigest()


class StructuralRepository:
    def __init__(self, connection, scope: StorageScope):
        if not isinstance(scope, StorageScope):
            raise StructuralScopeError("trusted storage scope required")
        self.connection, self.scope = connection, scope

    def _params(self, document_id, **extra):
        if type(document_id) is not int or document_id not in self.scope.document_ids:
            raise StructuralScopeError("document outside trusted storage scope")
        return dict(org=self.scope.organization_id,bot=self.scope.bot_id,doc=document_id,**extra)

    def _owner(self, source):
        if (source.organization_id,source.bot_id) != (self.scope.organization_id,self.scope.bot_id):
            raise StructuralScopeError("DTO identity differs from server scope")
        return self._params(source.document_id)

    def _row(self, sql, params):
        return self.connection.execute(text(sql),params).mappings().one_or_none()

    def _document_lock(self, doc):
        row=self._row("SELECT id,version,crawl_id,website_id,active_structure_revision_id,status,processing_status FROM documents "
            "WHERE organization_id=:org AND bot_id=:bot AND id=:doc FOR UPDATE",self._params(doc))
        if row is None: raise StructuralScopeError("scoped document unavailable")
        return row

    @staticmethod
    def _source(row):
        return SourceIdentity(organization_id=row["organization_id"],bot_id=row["bot_id"],document_id=row["document_id"],
            document_version_id=row["id"],source_version=row["source_version"],source_sha256=row["source_sha256"])

    def get_document_version(self, document_id, version_id):
        row=self._row("SELECT * FROM document_versions WHERE "+OWNER+" AND id=:version",self._params(document_id,version=version_id))
        if row is None: raise StructuralScopeError("scoped source version unavailable")
        return dict(row)

    def _source_identity(self, document_id, version_id):
        # Identity hydration must never load potentially large source artifacts.
        row=self._row("SELECT "+", ".join(SOURCE_COLUMNS)+" FROM document_versions WHERE "+OWNER+" AND id=:version",
                      self._params(document_id,version=version_id))
        if row is None:
            raise StructuralScopeError("scoped source version unavailable")
        return self._source(row)

    def _insert_idempotent(self, table, values, conflict_where, params):
        # Identifiers come only from private call-site dictionaries, never metadata.
        existing=self._row(f"SELECT * FROM {table} WHERE {conflict_where}",params)
        if existing is not None:
            if any(existing[k] != v for k,v in values.items()):
                raise StructuralConflict("immutable identity has different content")
            return False
        columns=", ".join(values)
        holders=", ".join(f"CAST(:{k} AS jsonb)" if k in JSON_FIELDS else f":{k}" for k in values)
        self.connection.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({holders})"),
            {k:_json(v) if k in JSON_FIELDS and v is not None else v for k,v in values.items()})
        return True

    def _insert_node_batch(self, rows):
        if not rows:
            return
        columns=tuple(rows[0])
        params={}
        groups=[]
        for i,row in enumerate(rows):
            holders=[]
            for key in columns:
                name=f"p{i}_{key}"
                holders.append(f"CAST(:{name} AS jsonb)" if key in JSON_FIELDS else f":{name}")
                value=row[key]
                params[name]=_json(value) if key in JSON_FIELDS and value is not None else value
            groups.append("("+", ".join(holders)+")")
        self.connection.execute(text("INSERT INTO structural_nodes ("+", ".join(columns)+") VALUES "+", ".join(groups)),params)

    def create_document_version(self, source: SourceIdentity, *, source_identity, source_format, fidelity,
                                source_text=None, source_artifact_ref=None, mime_type=None,
                                source_url=None, canonical_url=None):
        source=_validate(source,SourceIdentity); self._owner(source)
        if not isinstance(source_identity,str) or not source_identity:
            raise ValueError("explicit source identity required")
        if source_text is None and not source_artifact_ref:
            raise ValueError("owned source artifact/text required")
        if source_text is not None and sha256(source_text.encode("utf-8")).hexdigest()!=source.source_sha256:
            raise StructuralConflict("immutable source hash mismatch")
        with self.connection.begin_nested():
            current=self._document_lock(source.document_id)
            existing=self._row("SELECT * FROM document_versions WHERE "+OWNER+" AND id=:version",
                self._params(source.document_id,version=source.document_version_id))
            if existing is None and source.source_version!=current["version"]:
                raise StructuralConflict("source version is not current at capture")
            values=dict(organization_id=self.scope.organization_id,bot_id=self.scope.bot_id,document_id=source.document_id,
                id=source.document_version_id,source_version=source.source_version,source_sha256=source.source_sha256,
                crawl_id=existing["crawl_id"] if existing else current["crawl_id"],
                website_id=existing["website_id"] if existing else current["website_id"],source_identity=source_identity,
                source_format=source_format,fidelity=fidelity,source_text=source_text,source_artifact_ref=source_artifact_ref,
                mime_type=mime_type,source_url=source_url,canonical_url=canonical_url)
            self._insert_idempotent("document_versions",values,OWNER+" AND id=:version",
                self._params(source.document_id,version=source.document_version_id))
        return source

    def _revision_row(self, doc, rev, lock=False):
        row=self._row("SELECT * FROM document_structure_revisions WHERE "+OWNER+" AND id=:rev"+ (" FOR UPDATE" if lock else ""),
                      self._params(doc,rev=rev))
        if row is None: raise StructuralScopeError("scoped structural revision unavailable")
        return row

    def get_structure_revision(self, document_id, revision_id):
        row=self._revision_row(document_id,revision_id)
        source=self._source_identity(document_id,row["document_version_id"])
        return StructureRevisionDescriptor(identity=RevisionIdentity(source=source,structure_revision_id=revision_id),
            schema_version=row["schema_version"],parser_version=row["parser_version"],normalizer_version=row["normalizer_version"],
            chunker_version=row["chunk_policy_version"],configuration_sha256=row["configuration_sha256"],
            source_format=row["source_format"],fidelity=row["fidelity"],state=row["state"],quality=row["quality"])

    def create_structure_revision(self, descriptor: StructureRevisionDescriptor, counts: RevisionCounts, *, ingestion_job_id=None):
        descriptor=_validate(descriptor,StructureRevisionDescriptor);source=descriptor.identity.source;self._owner(source)
        if not isinstance(counts,RevisionCounts): raise ValueError("explicit expected counts required")
        with self.connection.begin_nested():
            self._document_lock(source.document_id)
            if self._source_identity(source.document_id,source.document_version_id)!=source:
                raise StructuralConflict("revision source mismatch")
            if ingestion_job_id is not None:
                job=self._row("SELECT id FROM ingestion_jobs WHERE id=:job AND organization_id=:org AND bot_id=:bot",
                              self._params(source.document_id,job=ingestion_job_id))
                if job is None: raise StructuralScopeError("scoped ingestion job unavailable")
            values=dict(organization_id=self.scope.organization_id,bot_id=self.scope.bot_id,document_id=source.document_id,
                document_version_id=source.document_version_id,id=descriptor.identity.structure_revision_id,
                build_fingerprint=descriptor.build_fingerprint(),schema_version=descriptor.schema_version,
                parser_version=descriptor.parser_version,normalizer_version=descriptor.normalizer_version,
                chunk_policy_version=descriptor.chunker_version,configuration_sha256=descriptor.configuration_sha256,
                source_format=descriptor.source_format,fidelity=descriptor.fidelity,ingestion_job_id=ingestion_job_id,
                quality=descriptor.quality.model_dump(mode="json"),source_sha256=source.source_sha256,
                expected_nodes=counts.nodes,expected_edges=counts.edges,expected_mappings=counts.mappings)
            by_build=self._row("SELECT * FROM document_structure_revisions WHERE "+OWNER+" AND document_version_id=:version AND build_fingerprint=:build",
                self._params(source.document_id,version=source.document_version_id,build=descriptor.build_fingerprint()))
            if by_build is not None:
                # Equivalent work has the original revision ID; callers must use it.
                if any(by_build[k]!=v for k,v in values.items() if k!="id"):
                    raise StructuralConflict("build fingerprint reused for different expected result")
                return self.get_structure_revision(source.document_id,by_build["id"])
            self._insert_idempotent("document_structure_revisions",values,OWNER+" AND id=:rev",
                self._params(source.document_id,rev=descriptor.identity.structure_revision_id))
        return self.get_structure_revision(source.document_id,descriptor.identity.structure_revision_id)

    def _writable(self, identity):
        self._owner(identity.source)
        self._document_lock(identity.source.document_id)
        row=self._revision_row(identity.source.document_id,identity.structure_revision_id,True)
        if row["state"]!="staging" or self.get_structure_revision(identity.source.document_id,identity.structure_revision_id).identity!=identity:
            raise StructuralConflict("revision is not matching writable staging")

    @staticmethod
    def _identity_values(identity):
        source=identity.source
        return dict(organization_id=source.organization_id,bot_id=source.bot_id,document_id=source.document_id,
                    document_version_id=source.document_version_id,structure_revision_id=identity.structure_revision_id)

    def stage_nodes(self, identity: RevisionIdentity, nodes):
        nodes=tuple(_validate(n,StructuralNode) for n in nodes);_bound(len(nodes),500)
        if any(n.identity.revision!=identity for n in nodes): raise StructuralScopeError("node batch identity mismatch")
        with self.connection.begin_nested():
            self._writable(identity)
            params=self._params(identity.source.document_id,rev=identity.structure_revision_id)
            parent_keys=list({n.parent.node_key for n in nodes if n.parent})
            parents={r["node_key"]:r for r in self.connection.execute(text("SELECT node_key,preorder,depth FROM structural_nodes WHERE "+REVISION+" AND node_key=ANY(:keys)"),dict(params,keys=parent_keys)).mappings()}
            existing={r["node_key"]:r for r in self.connection.execute(text("SELECT * FROM structural_nodes WHERE "+REVISION+" AND node_key=ANY(:keys)"),dict(params,keys=[n.identity.node_key for n in nodes])).mappings()}
            pending={}
            for n in sorted(nodes,key=lambda n:n.preorder):
                p=parents.get(n.parent.node_key) if n.parent else None
                if n.parent and p is None: raise StructuralConflict("parent must be staged before child")
                values=dict(self._identity_values(identity),node_key=n.identity.node_key,parent_key=n.parent.node_key if n.parent else None,
                    parent_preorder=p["preorder"] if p else None,parent_depth=p["depth"] if p else None,
                    depth=p["depth"]+1 if p else 0,preorder=n.preorder,leaf_order=n.leaf_order,parser_path=n.parser_path,
                    occurrence=n.occurrence,node_type=n.node_type.value,semantic_role=n.semantic_role.value,text=n.text,
                    attributes=n.attributes.model_dump(mode="json"),provenance=n.provenance.model_dump(mode="json"),
                    quality=n.quality.model_dump(mode="json") if n.quality else None,content_hash=sha256(n.text.encode()).hexdigest())
                prior=existing.get(n.identity.node_key) or pending.get(n.identity.node_key)
                if prior is not None:
                    if any(prior[k]!=v for k,v in values.items()):
                        raise StructuralConflict("immutable node identity has different content")
                else:
                    pending[n.identity.node_key]=values
                parents[n.identity.node_key]=values
            self._insert_node_batch(tuple(pending.values()))

    def stage_edges(self, identity: RevisionIdentity, edges):
        edges=tuple(_validate(e,StructuralEdge) for e in edges);_bound(len(edges),500)
        for edge in edges:
            if edge.from_node.revision!=identity: raise StructuralScopeError("edge origin mismatch")
            self._owner(edge.to_node.revision.source)
        with self.connection.begin_nested():
            self._writable(identity)
            params=self._params(identity.source.document_id,rev=identity.structure_revision_id)
            ordinal=self.connection.execute(text("SELECT COALESCE(max(ordinal),-1)+1 FROM structural_edges WHERE "+REVISION),params).scalar_one()
            for edge in sorted(edges,key=lambda e:e.canonical_json()):
                key=logical_edge_key(edge);target=edge.to_node.revision
                actual_source=self._source_identity(target.source.document_id,target.source.document_version_id)
                if actual_source!=target.source: raise StructuralConflict("edge target source identity mismatch")
                values=dict(self._identity_values(identity),from_node_key=edge.from_node.node_key,
                    to_document_id=target.source.document_id,to_document_version_id=target.source.document_version_id,
                    to_structure_revision_id=target.structure_revision_id,to_node_key=edge.to_node.node_key,edge_key=key,
                    relation=edge.relation.value,field=edge.field,role=edge.role.value if edge.role else None,
                    provenance=edge.provenance.model_dump(mode="json"),validation_state=edge.validation_state.value)
                existing=self._row("SELECT ordinal FROM structural_edges WHERE "+REVISION+" AND edge_key=:key",dict(params,key=key))
                values["ordinal"]=existing["ordinal"] if existing else ordinal
                if self._insert_idempotent("structural_edges",values,REVISION+" AND edge_key=:key",dict(params,key=key)): ordinal+=1

    def stage_chunk_mappings(self, identity: RevisionIdentity, mappings):
        mappings=tuple(_validate(m,ChunkStructuralMapping) for m in mappings);_bound(len(mappings),500)
        if any(m.node.revision!=identity for m in mappings): raise StructuralScopeError("mapping identity mismatch")
        with self.connection.begin_nested():
            self._writable(identity)
            for m in mappings:
                if not m.chunk_id.isascii() or not m.chunk_id.isdecimal() or int(m.chunk_id)<=0 or str(int(m.chunk_id))!=m.chunk_id:
                    raise ValueError("existing chunk IDs require canonical positive decimal form")
                values=dict(self._identity_values(identity),chunk_id=int(m.chunk_id),node_key=m.node.node_key,ordinal=m.ordinal,
                    node_start=m.node_slice.start,node_end=m.node_slice.end,output_start=m.output_slice.start,output_end=m.output_slice.end,
                    role=m.role,bundle_key=m.bundle_key,part_index=m.part_index,part_count=m.part_count)
                self._insert_idempotent("chunk_structural_nodes",values,"organization_id=:org AND bot_id=:bot AND chunk_id=:chunk AND ordinal=:ordinal",
                    self._params(identity.source.document_id,chunk=int(m.chunk_id),ordinal=m.ordinal))

    @staticmethod
    def _node(row, identity):
        return StructuralNode(identity=NodeIdentity(revision=identity,node_key=row["node_key"]),
            parent=NodeIdentity(revision=identity,node_key=row["parent_key"]) if row["parent_key"] else None,
            preorder=row["preorder"],leaf_order=row["leaf_order"],parser_path=row["parser_path"],occurrence=row["occurrence"],
            node_type=row["node_type"],semantic_role=row["semantic_role"],text=row["text"],attributes=row["attributes"],
            provenance=row["provenance"],quality=row["quality"])

    def list_nodes_bounded(self, document_id, revision_id, *, limit, after_preorder=-1, parent_key=None):
        _bound(limit)
        if type(after_preorder) is not int or after_preorder < -1: raise ValueError("invalid node cursor")
        identity=self.get_structure_revision(document_id,revision_id).identity
        rows=self.connection.execute(text("SELECT * FROM structural_nodes WHERE "+REVISION+
            " AND preorder>:after"+(" AND parent_key=:parent" if parent_key is not None else "")+" ORDER BY preorder LIMIT :limit"),
            self._params(document_id,rev=revision_id,after=after_preorder,parent=parent_key,limit=limit)).mappings()
        return tuple(self._node(r,identity) for r in rows)

    def get_node(self, document_id, revision_id, node_key):
        identity=self.get_structure_revision(document_id,revision_id).identity
        row=self._row("SELECT * FROM structural_nodes WHERE "+REVISION+" AND node_key=:key",self._params(document_id,rev=revision_id,key=node_key))
        return self._node(row,identity) if row is not None else None

    def _edge_rows(self, rows):
        rows=list(rows)
        if not rows: return ()
        versions={(r["document_id"],r["document_version_id"]) for r in rows}|{(r["to_document_id"],r["to_document_version_id"]) for r in rows}
        # One bounded version batch, not one lookup per edge.
        versions=sorted(versions)
        for doc,_ in versions:
            self._params(doc)
        # Bound arrays avoid a giant OR expression/driver parameter count when
        # validating an explicitly bounded, large management snapshot.
        source_rows=self.connection.execute(text("SELECT "+", ".join("v."+key for key in SOURCE_COLUMNS)+" FROM document_versions v JOIN unnest(CAST(:docs AS integer[]),CAST(:versions AS varchar[])) AS wanted(document_id,id) USING(document_id,id) WHERE v.organization_id=:org AND v.bot_id=:bot"),
            dict(org=self.scope.organization_id,bot=self.scope.bot_id,docs=[d for d,_ in versions],versions=[v for _,v in versions])).mappings()
        sources={(r["document_id"],r["id"]):self._source(r) for r in source_rows}
        output=[]
        for r in rows:
            a=RevisionIdentity(source=sources[(r["document_id"],r["document_version_id"])],structure_revision_id=r["structure_revision_id"])
            b=RevisionIdentity(source=sources[(r["to_document_id"],r["to_document_version_id"])],structure_revision_id=r["to_structure_revision_id"])
            output.append(StructuralEdge(from_node=NodeIdentity(revision=a,node_key=r["from_node_key"]),
                to_node=NodeIdentity(revision=b,node_key=r["to_node_key"]),relation=r["relation"],field=r["field"],role=r["role"],
                provenance=r["provenance"],validation_state=r["validation_state"]))
        return tuple(output)

    def list_edges_bounded(self, document_id, revision_id, *, node_key, limit, after_key="", reverse=False):
        _bound(limit);self._params(document_id)
        if type(reverse) is not bool or not isinstance(after_key,str): raise ValueError("invalid edge cursor/direction")
        prefix="to_" if reverse else ""
        doc_column=prefix+"document_id";rev_column=prefix+"structure_revision_id"
        node_column="to_node_key" if reverse else "from_node_key"
        rows=self.connection.execute(text(f"SELECT * FROM structural_edges WHERE organization_id=:org AND bot_id=:bot AND {doc_column}=:doc AND {rev_column}=:rev AND {node_column}=:node AND document_id=ANY(:allowed) AND to_document_id=ANY(:allowed) AND edge_key>:after ORDER BY edge_key LIMIT :limit"),
            self._params(document_id,rev=revision_id,node=node_key,allowed=sorted(self.scope.document_ids),after=after_key,limit=limit)).mappings()
        return self._edge_rows(rows)

    def list_chunk_mappings_bounded(self, document_id, revision_id, *, chunk_ids, limit, after=(0,-1)):
        _bound(limit);_bound(len(chunk_ids),64)
        if any(type(i) is not int or i<=0 for i in chunk_ids) or len(after)!=2 or any(type(i) is not int for i in after):
            raise ValueError("invalid mapping scope/cursor")
        identity=self.get_structure_revision(document_id,revision_id).identity
        rows=self.connection.execute(text("SELECT * FROM chunk_structural_nodes WHERE "+REVISION+
            " AND chunk_id=ANY(:chunks) AND (chunk_id,ordinal)>(:chunk,:ordinal) ORDER BY chunk_id,ordinal LIMIT :limit"),
            self._params(document_id,rev=revision_id,chunks=list(chunk_ids),chunk=after[0],ordinal=after[1],limit=limit)).mappings()
        return tuple(self._mapping(r,identity) for r in rows)

    @staticmethod
    def _mapping(row, identity):
        return ChunkStructuralMapping(node=NodeIdentity(revision=identity,node_key=row["node_key"]),chunk_revision=identity,
            chunk_id=str(row["chunk_id"]),ordinal=row["ordinal"],node_slice=ByteRange(start=row["node_start"],end=row["node_end"]),
            output_slice=ByteRange(start=row["output_start"],end=row["output_end"]),role=row["role"],bundle_key=row["bundle_key"],
            part_index=row["part_index"],part_count=row["part_count"])

    def load_revision_bounded(self, document_id, revision_id, *, node_limit, edge_limit, mapping_limit):
        """Explicit management/validation snapshot. Overflow is an error, not truncation."""
        _bound(node_limit,10000);_bound(edge_limit,20000);_bound(mapping_limit,100000)
        descriptor=self.get_structure_revision(document_id,revision_id)
        result={}
        for name,table,limit,order in (("nodes","structural_nodes",node_limit,"preorder"),("edges","structural_edges",edge_limit,"edge_key"),("mappings","chunk_structural_nodes",mapping_limit,"chunk_id,ordinal")):
            rows=list(self.connection.execute(text(f"SELECT * FROM {table} WHERE "+REVISION+f" ORDER BY {order} LIMIT :limit"),
                self._params(document_id,rev=revision_id,limit=limit+1)).mappings())
            if len(rows)>limit: raise StructuralConflict("structural snapshot exceeds explicit bound")
            result[name]=rows
        return StructuralDocument(revision=descriptor,nodes=tuple(self._node(r,descriptor.identity) for r in result["nodes"]),
            edges=self._edge_rows(result["edges"]),mappings=tuple(self._mapping(r,descriptor.identity) for r in result["mappings"]))

    def validate_revision_counts(self, document_id, revision_id):
        row=self._revision_row(document_id,revision_id)
        counts=[self.connection.execute(text(f"SELECT count(*) FROM {table} WHERE "+REVISION),self._params(document_id,rev=revision_id)).scalar_one()
                for table in ("structural_nodes","structural_edges","chunk_structural_nodes")]
        if counts!=[row["expected_nodes"],row["expected_edges"],row["expected_mappings"]]:
            raise StructuralConflict("structural counts incomplete")
        return RevisionCounts(*counts)

    def mark_revision_validated(self, document_id, revision_id):
        with self.connection.begin_nested():
            descriptor=self.get_structure_revision(document_id,revision_id);self._writable(descriptor.identity)
            counts=self.validate_revision_counts(document_id,revision_id)
            doc=self.load_revision_bounded(document_id,revision_id,node_limit=counts.nodes,edge_limit=max(1,counts.edges),mapping_limit=max(1,counts.mappings))
            normalized=sha256(_json({k:doc.model_dump(mode="json")[k] for k in ("nodes","edges","mappings")}).encode()).hexdigest()
            sealed=doc.model_copy(update={"revision":doc.revision.model_copy(update={"state":RevisionState.VALIDATED})})
            self.connection.execute(text("UPDATE document_structure_revisions SET state='validated',normalized_hash=:hash,serialization_hash=:serialized WHERE "+OWNER+" AND id=:rev"),
                self._params(document_id,rev=revision_id,hash=normalized,serialized=sealed.canonical_hash()))
        return self.get_structure_revision(document_id,revision_id)

    def _mark_terminal(self, document_id, revision_id, state):
        with self.connection.begin_nested():
            self._document_lock(document_id);row=self._revision_row(document_id,revision_id,True)
            if row["state"]==state: return
            if row["state"] not in ("staging","validated"): raise StructuralConflict("revision cannot transition to terminal state")
            self.connection.execute(text("UPDATE document_structure_revisions SET state=:state WHERE "+OWNER+" AND id=:rev"),self._params(document_id,rev=revision_id,state=state))

    def mark_revision_failed(self, document_id, revision_id):
        self._mark_terminal(document_id,revision_id,"failed")

    def mark_revision_cancelled(self, document_id, revision_id):
        self._mark_terminal(document_id,revision_id,"cancelled")

    def activate_revision(self, document_id, revision_id, *, expected_source_version, expected_active_revision_id):
        """Document row lock + compare-and-swap; caller commits, no chunks changed."""
        with self.connection.begin_nested():
            current=self._document_lock(document_id)
            if current["version"]!=expected_source_version or current["active_structure_revision_id"]!=expected_active_revision_id:
                raise StructuralConflict("structural activation compare-and-swap conflict")
            row=self._revision_row(document_id,revision_id,True)
            source=self.get_document_version(document_id,row["document_version_id"])
            if row["state"]!="validated" or (source["source_version"],source["crawl_id"],source["website_id"])!=(current["version"],current["crawl_id"],current["website_id"]):
                raise StructuralConflict("activation requires validated current source")
            if current["active_structure_revision_id"] is not None:
                self.connection.execute(text("UPDATE document_structure_revisions SET state='superseded' WHERE "+OWNER+" AND id=:old AND state='active'"),
                    self._params(document_id,old=current["active_structure_revision_id"]))
            self.connection.execute(text("UPDATE document_structure_revisions SET state='active' WHERE "+OWNER+" AND id=:rev"),self._params(document_id,rev=revision_id))
            self.connection.execute(text("UPDATE documents SET active_structure_revision_id=:rev WHERE organization_id=:org AND bot_id=:bot AND id=:doc"),self._params(document_id,rev=revision_id))

    def list_active_nodes(self, hard_scope, document_id, *, limit, after_preorder=-1):
        """Serving boundary uses existing READY/ACL/crawl/profile SQL, no copied predicates."""
        _bound(limit);self._params(document_id)
        if (hard_scope.organization_id,hard_scope.bot_id)!=(self.scope.organization_id,self.scope.bot_id):
            raise StructuralScopeError("hard scope differs from storage scope")
        if hard_scope.embedding_profile is None:
            raise StructuralScopeError("serving requires an explicit embedding profile")
        if type(after_preorder) is not int or after_preorder < -1:
            raise ValueError("invalid node cursor")
        from sqlalchemy.orm import Session
        from database.models import Chunk, Document
        from services.knowledge_scope import ready_chunks
        # Apply eligibility in the SAME SQL snapshot as the text read. Do not
        # hydrate an earlier list of chunk IDs and trust it after state changes.
        def relation(name, fields):
            return table(name,*(column(field) for field in fields.split()))
        n=relation("structural_nodes","organization_id bot_id document_id document_version_id structure_revision_id node_key preorder").alias("n")
        m=relation("chunk_structural_nodes","organization_id bot_id document_id document_version_id structure_revision_id node_key chunk_id").alias("m")
        r=relation("document_structure_revisions","organization_id bot_id document_id document_version_id id state").alias("r")
        v=relation("document_versions","organization_id bot_id document_id id source_version crawl_id website_id").alias("v")
        with Session(bind=self.connection) as session:
            eligible=ready_chunks(session.query(Chunk.id).join(Document,Chunk.document_id==Document.id),
                self.scope.bot_id,self.scope.organization_id,[document_id],hard_scope=hard_scope)
            eligible=eligible.join(m,and_(m.c.chunk_id==Chunk.id,m.c.organization_id==Chunk.organization_id,m.c.bot_id==Chunk.bot_id,
                m.c.document_id==Chunk.document_id,m.c.document_version_id==Chunk.document_version_id,m.c.structure_revision_id==Chunk.structure_revision_id))
            eligible=eligible.join(r,and_(r.c.organization_id==Document.organization_id,r.c.bot_id==Document.bot_id,r.c.document_id==Document.id,
                r.c.id==Document.active_structure_revision_id,r.c.id==m.c.structure_revision_id,r.c.document_version_id==m.c.document_version_id,r.c.state=='active'))
            eligible=eligible.join(v,and_(v.c.organization_id==r.c.organization_id,v.c.bot_id==r.c.bot_id,v.c.document_id==r.c.document_id,
                v.c.id==r.c.document_version_id,v.c.source_version==Document.version,v.c.crawl_id.is_not_distinct_from(Document.crawl_id),v.c.website_id.is_not_distinct_from(Document.website_id)))
            eligible=eligible.filter(*(getattr(m.c,key)==getattr(n.c,key) for key in
                ("organization_id","bot_id","document_id","document_version_id","structure_revision_id","node_key"))).correlate(n).exists()
            query=select(literal_column("n.*")).select_from(n).where(n.c.organization_id==self.scope.organization_id,n.c.bot_id==self.scope.bot_id,
                n.c.document_id==document_id,n.c.preorder>after_preorder,eligible,
                text("(n.quality IS NULL OR n.quality->>'disposition'='accept')")).order_by(n.c.preorder).limit(limit)
            rows=list(self.connection.execute(query).mappings())
        if not rows: return ()
        descriptor=self.get_structure_revision(document_id,rows[0]["structure_revision_id"])
        return tuple(self._node(r,descriptor.identity) for r in rows)
