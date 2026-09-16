"""Offline storage boundaries. Real constraints/races are tested on PostgreSQL."""
from dataclasses import replace
from hashlib import sha256
import unittest
from unittest.mock import Mock

from services.structural_document import (
    ByteRange, ChunkStructuralMapping, NodeIdentity, Provenance, RevisionIdentity,
    SourceIdentity, SourceLocation, SourceQuality, SourceSpan, StructuralDocument,
    StructuralEdge, StructuralNode, StructureRevisionDescriptor, ValidationState, make_node_key,
)
from services.structural_repository import (
    RevisionCounts, StorageScope, StructuralRepository, StructuralScopeError,
    _bound, logical_edge_key,
)


def bundle(doc=10, org=1, bot=1, version=1, revision="r1", parser="test-v1", chunk=None, version_id=None):
    """Explicit synthetic annotations; never parses or loads customer text."""
    content = "Heading\nRepeated text\nRepeated text"
    source = SourceIdentity(organization_id=org, bot_id=bot, document_id=doc,
        document_version_id=version_id or f"v{version}", source_version=version,
        source_sha256=sha256(content.encode()).hexdigest())
    identity = RevisionIdentity(source=source, structure_revision_id=revision)
    span = SourceSpan(source=source, location=SourceLocation(system="utf8_bytes",
        byte_range=ByteRange(start=0, end=len(content.encode()))))
    prov = Provenance(method="manual_annotation", method_version="test-v1", basis="synthetic annotation", spans=(span,))
    quality = SourceQuality(classification="usable", disposition="accept", detector_version="test-v1",
                            reason_codes=("synthetic_fixture",), evidence=(span,))
    descriptor = StructureRevisionDescriptor(identity=identity, parser_version=parser,
        normalizer_version="test-v1", configuration_sha256=sha256(parser.encode()).hexdigest(),
        source_format="text", fidelity="original", state="validated", quality=quality)
    nodes = []
    for i, (kind, value) in enumerate((("document", ""), ("heading", "Heading"),
                                     ("paragraph", "Repeated text"), ("paragraph", "Repeated text"))):
        key = NodeIdentity(revision=identity, node_key=make_node_key(source, f"/node/{i}", 0, value))
        nodes.append(StructuralNode(identity=key, parser_path=f"/node/{i}", occurrence=0,
            parent=nodes[0].identity if i else None, preorder=i, leaf_order=i-1 if i else None,
            node_type=kind, text=value, provenance=prov))
    edge = StructuralEdge(from_node=nodes[1].identity, to_node=nodes[2].identity,
        relation="HEADING_FOR", provenance=prov, validation_state="validated")
    mappings = () if chunk is None else (ChunkStructuralMapping(node=nodes[2].identity,
        chunk_revision=identity, chunk_id=str(chunk), ordinal=0,
        node_slice=ByteRange(start=0,end=13), output_slice=ByteRange(start=0,end=13), role="body"),)
    return content, StructuralDocument(revision=descriptor, nodes=tuple(nodes), edges=(edge,), mappings=mappings)


class StructuralRepositoryOffline(unittest.TestCase):
    def setUp(self):
        self.conn = Mock()
        self.repo = StructuralRepository(self.conn, StorageScope(1,1,frozenset({10})))
        self.content, self.doc = bundle()

    def test_scope_requires_explicit_trusted_type(self):
        with self.assertRaises(StructuralScopeError): StructuralRepository(self.conn,{"organization_id":1})
        self.conn.execute.assert_not_called()

    def test_scope_frozen_and_bounded(self):
        for value in (frozenset(),frozenset({True}),frozenset({0}),frozenset(range(1,10002)),{10}):
            with self.assertRaises(StructuralScopeError): StorageScope(1,1,value)
        with self.assertRaises(StructuralScopeError): StorageScope(True,1,frozenset({10}))

    def test_node_read_requires_document_permission(self):
        with self.assertRaises(StructuralScopeError): self.repo.get_node(11,"r1","a"*64)
        self.conn.execute.assert_not_called()

    def test_malicious_source_owner_rejected_before_sql(self):
        for kwargs in ({"org":2},{"bot":2},{"doc":20}):
            source=bundle(**kwargs)[1].revision.identity.source
            with self.assertRaises(StructuralScopeError):
                self.repo.create_document_version(source,source_identity="owned",source_format="text",fidelity="original",source_text=self.content)
        self.conn.execute.assert_not_called()

    def test_node_batch_cannot_replace_identity(self):
        with self.assertRaises(StructuralScopeError): self.repo.stage_nodes(self.doc.revision.identity,bundle(org=2)[1].nodes)
        self.conn.execute.assert_not_called()

    def test_mapping_batch_cannot_replace_identity(self):
        with self.assertRaises(StructuralScopeError): self.repo.stage_chunk_mappings(self.doc.revision.identity,bundle(doc=20,chunk=3)[1].mappings)
        self.conn.execute.assert_not_called()

    def test_source_hash_enforced_before_sql(self):
        with self.assertRaises(ValueError): self.repo.create_document_version(self.doc.revision.identity.source,
            source_identity="owned",source_format="text",fidelity="original",source_text="wrong")
        self.conn.execute.assert_not_called()

    def test_untrusted_dict_not_a_dto(self):
        with self.assertRaises(ValueError): self.repo.create_structure_revision(self.doc.revision.model_dump(),RevisionCounts(4,1,0))
        self.conn.execute.assert_not_called()

    def test_read_limit_required_and_capped(self):
        for limit in (None,True,0,-1,257,1.5):
            with self.assertRaises(ValueError): self.repo.list_nodes_bounded(10,"r1",limit=limit)
        self.conn.execute.assert_not_called()

    def test_edge_limit_capped(self):
        with self.assertRaises(ValueError): self.repo.list_edges_bounded(10,"r1",node_key="a",limit=257)
        self.conn.execute.assert_not_called()

    def test_chunk_list_capped(self):
        with self.assertRaises(ValueError): self.repo.list_chunk_mappings_bounded(10,"r1",chunk_ids=list(range(1,66)),limit=1)
        self.conn.execute.assert_not_called()

    def test_snapshot_has_explicit_caps(self):
        with self.assertRaises(ValueError): self.repo.load_revision_bounded(10,"r1",node_limit=10001,edge_limit=1,mapping_limit=1)
        self.conn.execute.assert_not_called()

    def test_node_write_batch_capped(self):
        with self.assertRaises(ValueError): self.repo.stage_nodes(self.doc.revision.identity,[self.doc.nodes[0]]*501)
        self.conn.execute.assert_not_called()

    def test_count_limits(self):
        for counts in ((0,0,0),(10001,0,0),(1,-1,0),(1,20001,0),(1,0,100001),(True,0,0)):
            with self.assertRaises(ValueError): RevisionCounts(*counts)

    def test_logical_edge_identity_ignores_confidence_state(self):
        edge=self.doc.edges[0]
        alternate=edge.model_copy(update={"provenance":edge.provenance.model_copy(update={"confidence":0.5}),"validation_state":ValidationState.UNVALIDATED})
        self.assertEqual(logical_edge_key(edge),logical_edge_key(alternate))

    def test_logical_edge_identity_pins_target(self):
        edge=self.doc.edges[0]
        alternate=edge.model_copy(update={"to_node":self.doc.nodes[3].identity})
        self.assertNotEqual(logical_edge_key(edge),logical_edge_key(alternate))

    def test_repeated_text_has_distinct_source_path_identity(self):
        self.assertEqual(self.doc.nodes[2].text,self.doc.nodes[3].text)
        self.assertNotEqual(self.doc.nodes[2].identity,self.doc.nodes[3].identity)

    def test_recipe_not_source_changes_processing_fingerprint(self):
        other=bundle(parser="test-v2")[1]
        self.assertEqual(other.revision.identity.source,self.doc.revision.identity.source)
        self.assertNotEqual(other.revision.build_fingerprint(),self.doc.revision.build_fingerprint())

    def test_scope_mismatch_serving_rejected_before_sql(self):
        from services.retrieval_contracts import HardKnowledgeScope
        with self.assertRaises(StructuralScopeError): self.repo.list_active_nodes(HardKnowledgeScope(2,1),10,limit=10)
        self.conn.execute.assert_not_called()

    def test_serving_requires_profile_and_valid_cursor(self):
        from services.retrieval_contracts import HardKnowledgeScope, ProfileIdentity
        with self.assertRaises(StructuralScopeError): self.repo.list_active_nodes(HardKnowledgeScope(1,1),10,limit=10)
        with self.assertRaises(ValueError): self.repo.list_active_nodes(
            HardKnowledgeScope(1,1,embedding_profile=ProfileIdentity("p","m",1,768)),10,limit=10,after_preorder=-2)
        self.conn.execute.assert_not_called()

    def test_no_commit_or_new_chunk_methods(self):
        import ast, inspect
        tree=ast.parse(inspect.getsource(StructuralRepository))
        self.assertFalse(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=="commit" for n in ast.walk(tree)))
        self.assertNotIn("INSERT INTO chunks",inspect.getsource(StructuralRepository))

    def test_identity_hydration_projects_no_artifact_text(self):
        source=self.doc.revision.identity.source
        row=dict(organization_id=1,bot_id=1,document_id=10,id="v1",source_version=1,source_sha256=source.source_sha256)
        self.conn.execute.return_value.mappings.return_value.one_or_none.return_value=row
        self.assertEqual(self.repo._source_identity(10,"v1"),source)
        sql=str(self.conn.execute.call_args.args[0])
        self.assertNotIn("SELECT *",sql)
        self.assertNotIn("source_text",sql)
        self.assertNotIn("source_artifact_ref",sql)


if __name__ == "__main__":
    unittest.main()
