"""Phase 4.1A pure offline contract, GOLD and metric boundary tests."""
import ast
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import unittest

from pydantic import ValidationError

from scripts.structural_gold_v1 import FIXTURE_DIR, build_fixture, fixture_specs, load_gold
from services.structural_document import (
    ByteRange, CellAttributes, ChunkStructuralMapping, CommercialAttributes, CommercialRole,
    CoordinateSystem, Disposition, LinkAttributes, NodeAttributes, NodeIdentity, NodeType,
    PageBox, Provenance, QualityClass, QuantityAttributes, Relation, RevisionIdentity,
    SemanticRole, SourceIdentity, SourceLocation, SourceQuality, SourceSpan,
    StructuralDocument, StructuralEdge, StructuralNode, StructureRevisionDescriptor,
    make_node_key,
)
from services.structural_metrics import compare_structures, provenance_completeness, serialization_coverage


GOLD = load_gold()
SPECS = {f["name"]: f for f in fixture_specs()}


def rebuild(value, **updates):
    data = value.model_dump(mode="json")
    data.update(updates)
    return type(value).model_validate(data)


def mapping(node, start=0, end=None, ordinal=0):
    end = len(node.text.encode()) if end is None else end
    return ChunkStructuralMapping(node=node.identity, chunk_revision=node.identity.revision,
        chunk_id="fixture-mapping-only", ordinal=ordinal, node_slice=ByteRange(start=start, end=end),
        output_slice=ByteRange(start=0, end=end-start), role="body")


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.doc = GOLD["hotel"]
        self.node = self.doc.nodes[1]
        self.source = self.doc.revision.identity.source

    def test_closed_node_vocabulary(self):
        self.assertEqual({e.value for e in NodeType}, set("document section heading paragraph list list_item table table_row table_cell group link media".split()))

    def test_closed_role_vocabulary(self):
        self.assertEqual({e.value for e in SemanticRole}, set("title faq_question faq_answer review product_card price_block directions ingredients timeline_stage warning navigation furniture unknown".split()))

    def test_closed_edge_vocabulary(self):
        self.assertEqual({e.value for e in Relation}, set("CONTAINS REFERS_TO VARIANT_OF DESCRIBES HEADING_FOR QA_PAIR".split()))

    def test_closed_quality_vocabulary(self):
        self.assertEqual({e.value for e in QualityClass}, set("usable mixed blocked interstitial navigation_only error unknown".split()))
        self.assertEqual({e.value for e in Disposition}, {"accept", "quarantine", "manual_review"})

    def test_unknown_node_type_rejected(self):
        with self.assertRaises(ValidationError): rebuild(self.node, node_type="product")

    def test_unknown_role_rejected(self):
        with self.assertRaises(ValidationError): rebuild(self.node, semantic_role="dosage_inference")

    def test_unknown_edge_rejected(self):
        with self.assertRaises(ValidationError): rebuild(self.doc.edges[0], relation="PARENT_OF")

    def test_schema_version_rejected(self):
        with self.assertRaises(ValidationError): rebuild(self.doc, schema_version="structural-v99")

    def test_every_ownership_component_mandatory(self):
        for key in self.source.model_fields:
            with self.subTest(key=key):
                data = self.source.model_dump(); del data[key]
                with self.assertRaises(ValidationError): SourceIdentity.model_validate(data)

    def test_identity_strict_positive_ids(self):
        for value in (None, 0, -1, True, "7"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError): rebuild(self.source, organization_id=value)

    def test_identity_cannot_be_overridden_by_metadata(self):
        with self.assertRaises(ValidationError): rebuild(self.node, metadata={"organization_id": 999})
        with self.assertRaises(ValidationError): NodeAttributes.model_validate({"organization_id": 999})

    def test_nested_values_frozen(self):
        with self.assertRaises(ValidationError): self.source.organization_id = 9
        with self.assertRaises(ValidationError): self.node.attributes.quantities = ()
        self.assertIsInstance(self.doc.nodes, tuple)
        self.assertIsInstance(self.node.provenance.spans, tuple)

    def test_node_key_deterministic(self):
        self.assertEqual(self.node.identity.node_key, make_node_key(self.source, self.node.parser_path, 0, self.node.text))

    def test_node_key_occurrence_not_only_text(self):
        self.assertNotEqual(make_node_key(self.source, "/a", 0, "repeat"), make_node_key(self.source, "/a", 1, "repeat"))

    def test_node_key_tenant_and_source_version(self):
        for other in (rebuild(self.source, organization_id=2), rebuild(self.source, source_version=2), rebuild(self.source, source_sha256="a"*64)):
            self.assertNotEqual(make_node_key(self.source, "/a", 0, "x"), make_node_key(other, "/a", 0, "x"))

    def test_invalid_node_key_rejected(self):
        data=self.node.model_dump(mode="json");data["identity"]["node_key"]="a"*64
        with self.assertRaises(ValidationError): StructuralNode.model_validate(data)

    def test_path_or_occurrence_changes_need_new_key(self):
        for changes in ({"parser_path":"/other"}, {"occurrence":1}, {"text":"other"}):
            with self.assertRaises(ValidationError): rebuild(self.node, **changes)

    def test_span_negative_and_reversed_rejected(self):
        for start,end in ((-1,2),(2,1),(True,2),(0,2.2)):
            with self.assertRaises(ValidationError): ByteRange(start=start,end=end)

    def test_half_open_empty_and_nonempty(self):
        self.assertEqual(ByteRange(start=0,end=0).end,0)
        self.assertEqual(ByteRange(start=2,end=5).end-2,3)

    def test_utf8_location_exclusive(self):
        with self.assertRaises(ValidationError): SourceLocation(system="utf8_bytes")
        with self.assertRaises(ValidationError): SourceLocation(system="utf8_bytes",byte_range=ByteRange(start=0,end=1),parser_item="a")

    def test_no_legacy_token_coordinate(self):
        with self.assertRaises(ValidationError): SourceLocation(system="enriched_token",byte_range=ByteRange(start=0,end=1))

    def test_parser_location_round_trip(self):
        x=SourceLocation(system="parser_item",parser_item="/body/7")
        self.assertEqual(x,SourceLocation.model_validate_json(x.canonical_json()))

    def test_bbox_round_trip(self):
        x=SourceLocation(system="page_bbox",page_bbox=PageBox(page=1,x0=0,y0=1,x1=20,y1=30,unit="points",origin="top_left"))
        self.assertEqual(x,SourceLocation.model_validate_json(x.canonical_json()))

    def test_bbox_invalid_ranges_and_nonfinite(self):
        for kwargs in ({"page":0},{"x0":4},{"x1":float("inf")},{"y1":float("nan")},{"unit":"normalized","x1":2}):
            data=dict(page=1,x0=0,y0=0,x1=1,y1=1,unit="points",origin="top_left");data.update(kwargs)
            with self.assertRaises(ValidationError): PageBox(**data)

    def test_unavailable_requires_reason(self):
        with self.assertRaises(ValidationError): SourceLocation(system="unavailable")
        self.assertEqual(SourceLocation(system="unavailable",unavailable_reason="not supplied").system,CoordinateSystem.UNAVAILABLE)

    def test_missing_provenance_rejected(self):
        data=self.node.model_dump(mode="json");del data["provenance"]
        with self.assertRaises(ValidationError): StructuralNode.model_validate(data)
        with self.assertRaises(ValidationError): rebuild(self.node.provenance,spans=[])

    def test_foreign_provenance_rejected(self):
        data=self.node.model_dump(mode="json");data["provenance"]["spans"][0]["source"]["document_id"]=9
        with self.assertRaises(ValidationError): StructuralNode.model_validate(data)

    def test_unknown_quality_not_accepted(self):
        q=self.doc.revision.quality
        for kind in ("unknown","blocked","interstitial","navigation_only","error"):
            with self.assertRaises(ValidationError): rebuild(q,classification=kind)
            self.assertEqual(rebuild(q,classification=kind,disposition="manual_review").classification.value,kind)

    def test_quality_requires_evidence_and_reason(self):
        for field in ("evidence","reason_codes"):
            with self.assertRaises(ValidationError): rebuild(self.doc.revision.quality,**{field:[]})

    def test_confidence_finite_and_bounded(self):
        for value in (-.1,1.1,float("nan"),float("inf")):
            with self.assertRaises(ValidationError): rebuild(self.node.provenance,confidence=value)

    def test_parent_different_revision_rejected(self):
        data=self.node.model_dump(mode="json");data["parent"]["revision"]["structure_revision_id"]="other"
        with self.assertRaises(ValidationError): StructuralNode.model_validate(data)

    def test_missing_parent_rejected(self):
        data=self.doc.model_dump(mode="json");data["nodes"][1]["parent"]["node_key"]="a"*64
        with self.assertRaises(ValidationError): StructuralDocument.model_validate(data)

    def test_parent_must_precede_child(self):
        data=self.doc.model_dump(mode="json");data["nodes"][1]["parent"]=data["nodes"][-1]["identity"]
        with self.assertRaises(ValidationError): StructuralDocument.model_validate(data)

    def test_duplicate_keys_and_preorders_rejected(self):
        data=self.doc.model_dump(mode="json");data["nodes"].append(data["nodes"][1])
        with self.assertRaises(ValidationError): StructuralDocument.model_validate(data)
        data=self.doc.model_dump(mode="json");data["nodes"][1]["preorder"]=0
        with self.assertRaises(ValidationError): StructuralDocument.model_validate(data)

    def test_exactly_one_root(self):
        data=self.doc.model_dump(mode="json");data["nodes"][1]["parent"]=None
        with self.assertRaises(ValidationError): StructuralDocument.model_validate(data)

    def test_root_must_be_document(self):
        data=self.doc.model_dump(mode="json");data["nodes"][0]["node_type"]="group"
        with self.assertRaises(ValidationError): StructuralDocument.model_validate(data)

    def test_leaf_order_unique_and_monotonic(self):
        data=self.doc.model_dump(mode="json");data["nodes"][1]["leaf_order"]=2;data["nodes"][2]["leaf_order"]=1
        with self.assertRaises(ValidationError): StructuralDocument.model_validate(data)
        data["nodes"][2]["leaf_order"]=2
        with self.assertRaises(ValidationError): StructuralDocument.model_validate(data)

    def test_complete_list_missing_item_rejected(self):
        data=GOLD["real_joint_full_list"].model_dump(mode="json");data["nodes"].pop()
        with self.assertRaises(ValidationError): StructuralDocument.model_validate(data)

    def test_edge_requires_full_endpoint_identity(self):
        data=self.doc.edges[0].model_dump(mode="json");data["to_node"]={"node_key":"a"*64}
        with self.assertRaises(ValidationError): StructuralEdge.model_validate(data)

    def test_edge_cross_tenant_or_bot_rejected(self):
        for field in ("organization_id","bot_id"):
            data=self.doc.edges[0].model_dump(mode="json");data["to_node"]["revision"]["source"][field]=55
            with self.assertRaises(ValidationError): StructuralEdge.model_validate(data)

    def test_cross_version_edge_explicit(self):
        data=self.doc.edges[0].model_dump(mode="json");data["to_node"]["revision"]["structure_revision_id"]="later"
        data["to_node"]["revision"]["source"]["source_version"]=2
        data["to_node"]["revision"]["source"]["document_version_id"]="v2"
        edge=StructuralEdge.model_validate(data)
        self.assertNotEqual(edge.from_node.revision,edge.to_node.revision)
        self.assertEqual(StructuralEdge.model_validate_json(edge.canonical_json()),edge)

    def test_local_edge_target_missing_rejected(self):
        data=self.doc.model_dump(mode="json");data["edges"][0]["to_node"]["node_key"]="a"*64
        with self.assertRaises(ValidationError): StructuralDocument.model_validate(data)

    def test_duplicate_edge_rejected(self):
        data=self.doc.model_dump(mode="json");data["edges"].append(data["edges"][0])
        with self.assertRaises(ValidationError): StructuralDocument.model_validate(data)

    def test_tree_parentage_not_semantic_contains(self):
        data=self.doc.model_dump(mode="json");e=data["edges"][0]
        e["from_node"]=data["nodes"][0]["identity"];e["relation"]="CONTAINS"
        with self.assertRaises(ValidationError): StructuralDocument.model_validate(data)

    def test_validated_edge_requires_located_evidence(self):
        data=self.doc.edges[0].model_dump(mode="json")
        data["provenance"]["spans"][0]["location"]={"system":"unavailable","unavailable_reason":"missing"}
        with self.assertRaises(ValidationError): StructuralEdge.model_validate(data)
        data["validation_state"]="unvalidated"
        self.assertEqual(StructuralEdge.model_validate(data).validation_state.value,"unvalidated")

    def test_qa_role_validation(self):
        data=self.doc.model_dump(mode="json");data["edges"][0]["relation"]="QA_PAIR"
        with self.assertRaises(ValidationError): StructuralDocument.model_validate(data)

    def test_attributes_not_open_metadata(self):
        with self.assertRaises(ValidationError): NodeAttributes.model_validate({"instructions":"execute"})
        with self.assertRaises(ValidationError): CommercialAttributes(source_text="$4",role="guessed_cheapest")

    def test_attribute_physical_type(self):
        with self.assertRaises(ValidationError): rebuild(self.node,attributes={"list":{"ordered":False,"item_count":0,"source_block_complete":True}})

    def test_commercial_unknown_no_inference(self):
        c=CommercialAttributes(source_text="$4",amount="4")
        self.assertIsNone(c.currency);self.assertEqual(c.role,CommercialRole.UNKNOWN)

    def test_amount_string_not_float_or_formula(self):
        for amount in (4.1,"NaN","1e2","3/2","$4",True):
            with self.assertRaises(ValidationError): CommercialAttributes(source_text="source",amount=amount)

    def test_quantity_unknown_units_preserved(self):
        q=QuantityAttributes(source_text="two flurbs",value="2",unit="flurbs")
        self.assertEqual(q.unit,"flurbs");self.assertIsNone(q.frequency)

    def test_quantity_unknown_value_preserved(self):
        q=QuantityAttributes(source_text="one portion as needed",unit=None)
        self.assertIsNone(q.value);self.assertIsNone(q.unit)

    def test_quantity_range_coherence(self):
        for data in ({"range_min":"2"},{"range_min":"3","range_max":"2"},{"value":"1","range_min":"1","range_max":"2"}):
            with self.assertRaises(ValidationError): QuantityAttributes(source_text="source",**data)

    def test_unknown_link_safety_rejected(self):
        with self.assertRaises(ValidationError): LinkAttributes(original_href="x",anchor_text="x",safety="trusted_by_model")

    def test_unsafe_schemes_cannot_be_claimed_safe(self):
        for href in ("javascript:alert(1)","file:///tmp/x","https://u:p@example.test/","https://example.test/\nfoo"):
            with self.assertRaises(ValidationError): LinkAttributes(original_href=href,anchor_text="x",safety="safe",validated_href=href)

    def test_unknown_unsafe_link_retained_not_resolved(self):
        link=LinkAttributes(original_href="javascript:alert(1)",anchor_text="x",safety="unsafe")
        self.assertIsNone(link.validated_href);self.assertEqual(link.resolution,"unresolved")

    def test_link_query_and_fragment_not_truncated(self):
        href="https://example.test/item?variant=blue#section"
        x=LinkAttributes(original_href=href,validated_href=href,anchor_text="Item",fragment="section",safety="safe")
        self.assertEqual(LinkAttributes.model_validate_json(x.canonical_json()).original_href,href)

    def test_table_header_missing_rejected(self):
        data=GOLD["table"].model_dump(mode="json");data["nodes"][-1]["attributes"]["cell"]["header_keys"]=["a"*64]
        with self.assertRaises(ValidationError): StructuralDocument.model_validate(data)

    def test_table_cell_bounds_rejected(self):
        data=GOLD["table"].model_dump(mode="json");data["nodes"][-1]["attributes"]["cell"]["column"]=2
        with self.assertRaises(ValidationError): StructuralDocument.model_validate(data)

    def test_mapping_requires_same_identity(self):
        data=mapping(self.node).model_dump(mode="json");data["chunk_revision"]["source"]["organization_id"]=9
        with self.assertRaises(ValidationError): ChunkStructuralMapping.model_validate(data)

    def test_mapping_bounds_rejected(self):
        m=mapping(self.node,end=1000)
        with self.assertRaises(ValidationError): rebuild(self.doc,mappings=[m.model_dump(mode="json")])

    def test_mapping_bundle_requires_all_fields(self):
        with self.assertRaises(ValidationError): rebuild(mapping(self.node),bundle_key="parts")
        with self.assertRaises(ValidationError): rebuild(mapping(self.node),bundle_key="parts",part_count=2,part_index=2)

    def test_mapping_duplicate_ordinal_rejected(self):
        m=mapping(self.node).model_dump(mode="json")
        with self.assertRaises(ValidationError): rebuild(self.doc,mappings=[m,m])

    def test_mapping_cannot_split_utf8_character(self):
        doc=GOLD["real_joint_full_list"]
        node=next(n for n in doc.nodes if "®" in n.text)
        start=node.text.encode().index("®".encode())+1
        with self.assertRaises(ValidationError): rebuild(doc,mappings=[mapping(node,start=start).model_dump(mode="json")])

    def test_foreign_revision_member_rejected(self):
        data=self.doc.model_dump(mode="json")
        data["revision"]["identity"]["structure_revision_id"]="other"
        with self.assertRaises(ValidationError): StructuralDocument.model_validate(data)

    def test_foreign_quality_source_rejected(self):
        data=self.doc.revision.model_dump(mode="json")
        data["quality"]["evidence"][0]["source"]["bot_id"]=9
        with self.assertRaises(ValidationError): StructureRevisionDescriptor.model_validate(data)

    def test_cross_table_header_rejected(self):
        spec=deepcopy(SPECS["table"])
        spec["annotations"] += [dict(label="second-table",text="",node_type="table",semantic_role="unknown",parent="root",attributes={"table":{"row_count":1,"column_count":1}},start=0,end=0),
            dict(label="second-row",text="",node_type="table_row",semantic_role="unknown",parent="second-table",attributes={},start=0,end=0),
            dict(label="second-cell",text="Name",node_type="table_cell",semantic_role="unknown",parent="second-row",attributes={"cell":{"row":0,"column":0,"header_labels":["cell00"]}},start=0,end=4)]
        with self.assertRaises(ValidationError): build_fixture(spec)

    def test_tree_depth_bound(self):
        spec=deepcopy(SPECS["malformed_markdown"]);spec["annotations"]=[]
        for i in range(33):
            spec["annotations"].append(dict(label="n"+str(i),text="",node_type="group",semantic_role="unknown",parent="root" if i==0 else "n"+str(i-1),attributes={},start=0,end=0))
        with self.assertRaises(ValidationError): build_fixture(spec)

    def test_canonical_node_edge_order_independent(self):
        doc=GOLD["timeline"]
        actual=rebuild(doc,nodes=list(reversed(doc.model_dump(mode="json")["nodes"])),edges=list(reversed(doc.model_dump(mode="json")["edges"])))
        self.assertEqual(doc.canonical_json(),actual.canonical_json())

    def test_dictionary_insertion_not_identity(self):
        data=self.doc.model_dump(mode="json")
        self.assertEqual(StructuralDocument.model_validate(dict(reversed(list(data.items())))).canonical_hash(),self.doc.canonical_hash())

    def test_build_fingerprint_not_lifecycle(self):
        revision=self.doc.revision
        self.assertEqual(rebuild(revision,state="active").build_fingerprint(),revision.build_fingerprint())
        self.assertNotEqual(rebuild(revision,parser_version="v2").build_fingerprint(),revision.build_fingerprint())

    def test_contract_import_has_no_runtime_dependencies(self):
        code="from services import structural_document, structural_metrics; import sys; assert not any(m.startswith(('sqlalchemy', 'database', 'docling', 'services.rag_', 'httpx', 'requests')) for m in sys.modules)"
        proc=subprocess.run([sys.executable,"-B","-c",code],capture_output=True,text=True,cwd=Path(__file__).parent)
        self.assertEqual(proc.returncode,0,proc.stderr)

    def test_contracts_have_no_eval_exec_or_io_calls(self):
        for name in ("structural_document.py","structural_metrics.py"):
            tree=ast.parse((Path(__file__).parent/"services"/name).read_text(encoding="utf-8"))
            calls=[n.func.id for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)]
            self.assertFalse(set(calls)&{"eval","exec","open","compile","__import__"})


class GoldAndMetricsTests(unittest.TestCase):
    def test_frozen_manifest(self):
        manifest=json.loads((FIXTURE_DIR/"manifest.json").read_text())
        self.assertEqual(set(manifest["fixtures"]),set(GOLD))
        for name,doc in GOLD.items(): self.assertEqual(doc.canonical_hash(),manifest["fixtures"][name],name)
        for filename,digest in manifest["source_files"].items():
            self.assertEqual(sha256((FIXTURE_DIR/filename).read_bytes().replace(b"\r\n",b"\n")).hexdigest(),digest)

    def test_required_inventory(self):
        self.assertEqual(sum(f["category"]=="real_saved_source" for f in SPECS.values()),11)
        self.assertEqual(sum(f["category"]=="synthetic" for f in SPECS.values()),8)
        self.assertEqual(sum(f["category"]=="adversarial" for f in SPECS.values()),11)

    def test_real_complete_lists_not_highlight_cards(self):
        for name,count in (("real_joint_full_list",7),("real_complex_full_list",5),("real_mycovital_full_list",4)):
            doc=GOLD[name];items=[n for n in doc.nodes if n.node_type==NodeType.LIST_ITEM]
            self.assertEqual(len(items),count)
            self.assertEqual(compare_structures(doc,doc)["full_list"].recall,1)

    def test_real_reviews_different_pinned_targets(self):
        self.assertEqual(GOLD["real_review_mycovital"].edges[0].to_node.revision.source.document_id,29)
        self.assertEqual(GOLD["real_review_chocolate"].edges[0].to_node.revision.source.document_id,25)

    def test_real_timeline_three_stages_and_qualification(self):
        stages=[n for n in GOLD["real_chocolate_timeline"].nodes if n.attributes.timeline]
        self.assertEqual([n.attributes.timeline.stage_order for n in stages],[0,1,2])
        self.assertEqual([n.attributes.timeline.stage_label for n in stages],["1-2 MONTHS","3-4 MONTHS","5-6 MONTHS"])
        self.assertIn("no specific",stages[-1].attributes.timeline.qualifiers[0])

    def test_resveratrol_no_invented_currency_or_role(self):
        prices=[n.attributes.commercial for n in GOLD["real_resveratrol_offers"].nodes if n.attributes.commercial]
        self.assertEqual([p.amount for p in prices],["55.20","44.16","55.20","1.47","55.20","44.16"])
        self.assertTrue(all(p.role==CommercialRole.UNKNOWN and p.currency is None for p in prices))

    def test_mixed_source_not_blanket_blocked(self):
        doc=GOLD["real_blocked_witness"]
        self.assertEqual(doc.revision.quality.classification,QualityClass.MIXED)
        self.assertEqual(doc.nodes[1].quality.classification,QualityClass.BLOCKED)

    def test_repeated_text_does_not_collapse(self):
        a,b=GOLD["repeated_text"].nodes[1:]
        self.assertEqual(a.text,b.text);self.assertNotEqual(a.identity,b.identity)
        self.assertNotEqual(a.provenance.spans,b.provenance.spans)

    def test_duplicate_headings_different_bodies(self):
        doc=GOLD["duplicate_headings"]
        self.assertEqual(len(doc.edges),2);self.assertNotEqual(doc.edges[0].to_node,doc.edges[1].to_node)

    def test_ambiguous_and_unsafe_links_no_edges(self):
        for name in ("ambiguous_link","unsafe_link","review_near_wrong_link"):
            self.assertEqual(GOLD[name].edges,())

    def test_long_units_not_truncated(self):
        for name in ("long_list_item","long_table_cell"):
            n=max(GOLD[name].nodes,key=lambda n:len(n.text))
            self.assertGreater(len(n.text),20000);self.assertTrue(n.text.endswith("end."))

    def test_prompt_injection_remains_plain_text(self):
        doc=GOLD["prompt_injection"]
        self.assertIn("DROP TABLE",doc.nodes[1].text)
        self.assertEqual(doc.revision.identity.source.organization_id,70001)
        self.assertEqual(doc.edges,())

    def test_saved_excerpt_hash_tampering_fails(self):
        spec=deepcopy(SPECS["real_joint_full_list"]);spec["source_text"]+="changed"
        with self.assertRaises(ValueError): build_fixture(spec)

    def test_heading_loss_detected(self):
        doc=GOLD["hotel"];actual=rebuild(doc,edges=[])
        self.assertEqual(compare_structures(doc,actual)["heading_body"].recall,0)

    def test_missing_list_detected(self):
        doc=GOLD["real_joint_full_list"]
        data=doc.model_dump(mode="json");data["nodes"][1]["attributes"]["list"]["source_block_complete"]=False;data["nodes"].pop()
        metric=compare_structures(doc,StructuralDocument.model_validate(data))["full_list"]
        self.assertEqual(metric.recall,0);self.assertIsNone(metric.precision)

    def test_wrong_review_edge_penalizes_precision_and_recall(self):
        doc=GOLD["reviews"];data=doc.model_dump(mode="json")
        data["edges"][0]["to_node"]=data["edges"][1]["to_node"]
        m=compare_structures(doc,StructuralDocument.model_validate(data))["review_edges"]
        self.assertEqual(m.precision,.5);self.assertEqual(m.recall,.5)

    def test_no_edges_not_false_success(self):
        doc=GOLD["reviews"];m=compare_structures(doc,rebuild(doc,edges=[]))["review_edges"]
        self.assertEqual(m.recall,0);self.assertIsNone(m.precision)

    def test_empty_expected_metric_is_not_perfect_score(self):
        doc=GOLD["malformed_markdown"];m=compare_structures(doc,doc)["review_edges"]
        self.assertIsNone(m.precision);self.assertIsNone(m.recall)

    def test_price_role_change_detected(self):
        doc=GOLD["software_plan"];data=doc.model_dump(mode="json")
        next(n for n in data["nodes"] if n["attributes"]["commercial"])["attributes"]["commercial"]["role"]="one_time"
        self.assertEqual(compare_structures(doc,StructuralDocument.model_validate(data))["price_role"].recall,0)

    def test_described_price_subject_change_detected(self):
        doc=GOLD["software_plan"]
        price=next(n for n in doc.nodes if n.attributes.commercial)
        edge=StructuralEdge(from_node=price.identity,to_node=doc.nodes[0].identity,relation="DESCRIBES",field="price",provenance=price.provenance,validation_state="validated")
        expected=rebuild(doc,edges=[e.model_dump(mode="json") for e in doc.edges]+[edge.model_dump(mode="json")])
        altered=rebuild(edge,to_node=doc.nodes[1].identity.model_dump(mode="json"))
        actual=rebuild(doc,edges=[e.model_dump(mode="json") for e in doc.edges]+[altered.model_dump(mode="json")])
        self.assertEqual(compare_structures(expected,actual)["price_role"].recall,0)

    def test_quantity_frequency_loss_detected(self):
        doc=GOLD["real_quantity_mycovital"];data=doc.model_dump(mode="json")
        data["nodes"][1]["attributes"]["quantities"][0]["frequency"]=None
        self.assertEqual(compare_structures(doc,StructuralDocument.model_validate(data))["quantity_unit"].recall,.5)

    def test_timeline_qualifier_loss_detected(self):
        doc=GOLD["timeline"];data=doc.model_dump(mode="json")
        next(n for n in data["nodes"] if n["attributes"]["timeline"])["attributes"]["timeline"]["qualifiers"]=[]
        self.assertEqual(compare_structures(doc,StructuralDocument.model_validate(data))["timeline_stage"].recall,.5)

    def test_link_loss_detected(self):
        doc=GOLD["real_canonical_link"];actual=rebuild(doc,nodes=[doc.nodes[0].model_dump(mode="json")])
        self.assertEqual(compare_structures(doc,actual)["canonical_link"].recall,0)

    def test_provenance_unavailable_honest_but_not_located(self):
        doc=GOLD["missing_location"]
        self.assertEqual(provenance_completeness(doc).recall,0)
        self.assertEqual(compare_structures(doc,doc)["provenance"].recall,1)

    def test_cross_tenant_metric_comparison_forbidden(self):
        with self.assertRaises(ValueError): compare_structures(GOLD["hotel"],GOLD["course"])

    def test_mapping_coverage_empty_partial_full_and_overlap(self):
        doc=GOLD["malformed_markdown"];node=doc.nodes[1];size=len(node.text.encode())
        self.assertEqual(serialization_coverage(doc).recall,0)
        partial=rebuild(doc,mappings=[mapping(node,end=5).model_dump(mode="json")])
        self.assertEqual(serialization_coverage(partial).matched,5)
        full=rebuild(doc,mappings=[mapping(node).model_dump(mode="json"),mapping(node,start=1,end=5,ordinal=1).model_dump(mode="json")])
        self.assertEqual(serialization_coverage(full).matched,size)
        self.assertEqual(serialization_coverage(full).recall,1)


def _fixture_round_trip(name):
    def test(self):
        doc=GOLD[name]
        self.assertEqual(StructuralDocument.model_validate_json(doc.canonical_json()),doc)
        for metric in compare_structures(doc,doc).values():
            self.assertEqual(metric.matched,metric.expected)
        spec=SPECS[name];raw=spec["source_text"].encode()
        for node in doc.nodes:
            for span in node.provenance.spans:
                if span.location.system==CoordinateSystem.UTF8_BYTES:
                    start=span.location.byte_range.start-spec["source_start"]
                    end=span.location.byte_range.end-spec["source_start"]
                    self.assertGreaterEqual(start,0);self.assertLessEqual(end,len(raw))
                    if node.text: self.assertEqual(raw[start:end].decode(),node.text)
    return test


for _name in GOLD:
    setattr(GoldAndMetricsTests,"test_round_trip_"+_name,_fixture_round_trip(_name))


def _enum_round_trip(field,value):
    def test(self):
        if field=="relation":
            original=GOLD["hotel"].edges[0]
        else:
            original=GOLD["hotel"].nodes[1]
        changed=rebuild(original,**{field:value.value})
        self.assertEqual(type(changed).model_validate_json(changed.canonical_json()),changed)
    return test


for _field,_enum in (("node_type",NodeType),("semantic_role",SemanticRole),("relation",Relation)):
    for _value in _enum:
        setattr(ContractTests,"test_enum_round_trip_"+_field+"_"+_value.value,_enum_round_trip(_field,_value))


if __name__=="__main__":
    unittest.main()
