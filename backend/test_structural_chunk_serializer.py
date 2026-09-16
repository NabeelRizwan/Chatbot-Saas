"""Offline serializer contracts, frozen witnesses and real parser integration."""
import ast
from hashlib import sha256
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from scripts.evaluate_structural_chunk_serializer import metrics
from scripts.evaluate_structural_text_adapter import parse_source
from scripts.structural_chunk_gold_v1 import build, specs, FIXTURE
from scripts.structural_gold_v1 import load_gold
from services.structural_chunking import (
    ChunkPolicy, SerializationError, local_tokenizer, count_tokens,
    serialize_structural_document as serialize,
)
from services.structural_document import StructuralDocument, SemanticRole


ROOT = Path(__file__).resolve().parents[1]


def fixture(name):
    return build(next(s for s in specs() if s['name'] == name))


class ChunkContracts(unittest.TestCase):
    def assert_complete(self, batch):
        m = metrics(batch)
        self.assertEqual(m['unaccounted_bytes'], 0)
        self.assertTrue(m['mapping_exact'])
        self.assertTrue(m['hard_cap'])
        self.assertLessEqual(m['max_prefix_tokens'], 80)
        self.assertTrue(m['timeline_stage_separation'])
        for field in ('headings','lists','list_items','cells','headers','reviews',
                      'faq_questions','timeline_stages','commercial','quantities','warnings'):
            self.assertEqual(m[field]['expected'], m[field]['retained'], field)

    def test_simple_prose(self):
        batch = serialize(parse_source('A quiet room.'))
        self.assertEqual(len(batch.chunks), 1)
        self.assertEqual(batch.chunks[0].text, 'A quiet room.')

    def test_nested_heading_context(self):
        doc = parse_source('# Guide\n\n## Rooms\n\n### Quiet area\n\nUse the desk.')
        c = serialize(doc).chunks[-1]
        self.assertEqual(len(c.heading_path), 3)
        self.assertTrue(c.text.startswith('# Guide\n## Rooms\n### Quiet area\n'))

    def test_long_heading_metadata_not_summary(self):
        title = '# '+'UnusuallyLongHeading '*100
        b = serialize(parse_source(title+'\n\nA quiet room.'))
        c = b.chunks[-1]
        self.assertEqual(len(c.heading_path), 1)
        self.assertEqual(c.text, 'A quiet room.')
        self.assert_complete(b)

    def test_compatible_paragraphs_merge(self):
        b = serialize(parse_source('# Guide\n\nFirst room.\n\nSecond room.'))
        self.assertEqual(len([c for c in b.chunks if c.kind=='prose']),1)

    def test_subject_boundaries(self):
        d = load_gold()['reviews']
        b = serialize(d)
        review = [c for c in b.chunks if c.kind=='review']
        self.assertGreaterEqual(len(review), 2)
        self.assertEqual(len({c.bundle_key for c in review}), len(review))

    def test_section_nonmerge(self):
        b = serialize(fixture('duplicate_headings'))
        prose = [c for c in b.chunks if c.kind=='prose']
        self.assertEqual(len(prose), 2)
        self.assertNotEqual(prose[0].heading_path, prose[1].heading_path)

    def test_faq_together(self):
        b = serialize(fixture('faq'))
        q = [c for c in b.chunks if c.kind=='faq']
        self.assertEqual(len(q),1)
        self.assertIn('How can I use the room?',q[0].text)
        self.assertIn('participant',q[0].text)

    def test_faq_question_repeated(self):
        b = serialize(fixture('huge_faq'))
        parts = [c for c in b.chunks if c.kind=='faq']
        self.assertGreater(len(parts),1)
        self.assertTrue(all('How can I use the room?' in c.text for c in parts))

    def test_list_indices_exact_and_complete(self):
        b = serialize(fixture('huge_list'))
        parts = [c for c in b.chunks if c.kind=='list']
        indices = [i for c in parts for _,i in c.list_item_indices]
        self.assertEqual(indices, list(range(260)))
        self.assertTrue(all(c.source_block_complete for c in parts))
        self.assertEqual(len({c.bundle_key for c in parts}),1)

    def test_huge_item_continuations(self):
        b = serialize(fixture('huge_item'))
        parts = [c for c in b.chunks if c.kind=='list']
        self.assertGreater(sum(any(i==0 for _,i in c.list_item_indices) for c in parts),1)
        self.assert_complete(b)

    def test_nested_list_identity(self):
        b = serialize(fixture('nested_list'))
        self.assertGreater(len({k for c in b.chunks for k,_ in c.list_item_indices}),1)

    def test_table_header_repetition_is_inherited(self):
        b = serialize(fixture('huge_table'))
        parts = [c for c in b.chunks if c.kind=='table']
        self.assertGreater(len(parts),1)
        for c in parts[1:]:
            self.assertIn('Capacity',c.text)
            self.assertTrue(any(m.usage=='inherited' and m.mapping.role=='header' for m in c.mappings))

    def test_rows_not_split_when_bounded(self):
        b = serialize(fixture('huge_table'))
        nodes={n.identity:n for n in b.source_graph.nodes}
        places={}
        for c in b.chunks:
            for i in c.table_cells:
                row=nodes[i].attributes.cell.row
                if row:
                    places.setdefault(row,set()).add(c.chunk_key)
        self.assertTrue(all(len(v)==1 for v in places.values()))

    def test_timeline_qualifier_repeated(self):
        b = serialize(fixture('long_stage'))
        parts = [c for c in b.chunks if c.kind=='timeline_stage' and c.part_count>1]
        self.assertTrue(parts)
        self.assertTrue(all('Results vary.' in c.text for c in parts))

    def test_price_role_attributes_unchanged(self):
        d = load_gold()['real_resveratrol_offers']
        b = serialize(d)
        self.assertEqual(d.canonical_json(), b.source_graph.canonical_json())
        self.assert_complete(b)

    def test_multiple_amounts_not_merged(self):
        b = serialize(fixture('commercial'))
        self.assertEqual(len([c for c in b.chunks if c.kind=='price_block']),2)

    def test_quantities_and_frequency_unchanged(self):
        d = fixture('quantity')
        b = serialize(d)
        self.assertEqual(d.nodes, b.source_graph.nodes)
        self.assertIn('2 capsules daily with 8 oz water', b.chunks[-1].text)

    def test_warning_not_positive_merge(self):
        b = serialize(fixture('warning_boundary'))
        self.assertEqual([c.kind for c in b.chunks], ['heading','prose','warning','prose'])

    def test_review_reference_retained(self):
        d = load_gold()['real_review_chocolate']
        b = serialize(d)
        self.assertEqual(b.source_graph.edges, d.edges)
        self.assertGreater(metrics(b)['review_reference_edges'],0)

    def test_safe_link_whole(self):
        b = serialize(fixture('safe_link'))
        self.assertIn('[the workshop](https://example.org/workshop#rooms)',b.chunks[-1].text)

    def test_long_link_only_metadata(self):
        b = serialize(fixture('long_link'))
        self.assertTrue(any(x.reason=='link_metadata_only' for x in b.excluded))
        self.assertFalse(any('https://' in c.text for c in b.chunks))
        self.assertTrue(any(n.attributes.link and len(n.attributes.link.original_href)>1000 for n in b.source_graph.nodes))

    def test_unsafe_link_not_serialized(self):
        b=serialize(fixture('unsafe_link'))
        self.assertFalse(any('javascript:' in c.text for c in b.chunks))
        self.assert_complete(b)

    def test_unsafe_heading_not_inherited(self):
        b=serialize(parse_source('# [Guide](javascript:alert)\n\nA quiet room.'))
        self.assertFalse(any('javascript:' in c.text for c in b.chunks))
        self.assert_complete(b)

    def test_split_links_not_broken(self):
        d=parse_source('# Guide\n\n'+'Sentence. '*650+'[whole](https://example.org/end)'+'Sentence. '*200)
        b=serialize(d)
        self.assertEqual(sum('[whole](https://example.org/end)' in c.text for c in b.chunks),1)
        self.assertFalse(any('[whole](' in c.text and '[whole](https://example.org/end)' not in c.text for c in b.chunks))

    def test_node_local_splits_cover_whole(self):
        b=serialize(fixture('long_sentence'))
        self.assert_complete(b)
        self.assertTrue(any(m.mapping.node_slice.start>0 for c in b.chunks for m in c.mappings if m.usage=='primary'))

    def test_heading_mapping_role(self):
        b=serialize(fixture('prose'))
        self.assertTrue(any(m.usage=='inherited' and m.mapping.role=='heading' for c in b.chunks for m in c.mappings))

    def test_overlap_exact_and_bounded(self):
        b=serialize(fixture('long_paragraph'))
        spans=[(c,m) for c in b.chunks for m in c.mappings if m.usage=='overlap']
        self.assertTrue(spans)
        for c,m in spans:
            r=m.mapping.output_slice
            self.assertLessEqual(count_tokens(c.text.encode()[r.start:r.end].decode()),60)

    def test_duplicate_occurrences_distinct(self):
        b=serialize(fixture('repeated_paragraphs'))
        matches=[n.identity for n in b.source_graph.nodes if n.text=='A quiet room.']
        self.assertEqual(len(matches),2)
        self.assertNotEqual(*matches)
        self.assertTrue(all(any(m.mapping.node==i for c in b.chunks for m in c.mappings) for i in matches))

    def test_target_range(self):
        b=serialize(fixture('long_paragraph'))
        interior=[c.token_count for c in b.chunks[1:-1]]
        self.assertTrue(all(250<=v<=650 for v in interior))

    def test_policy_fingerprint(self):
        d=fixture('prose')
        a=serialize(d)
        b=serialize(d,ChunkPolicy(target=400))
        self.assertNotEqual(a.recipe_hash,b.recipe_hash)
        self.assertNotEqual(a.chunks[0].chunk_key,b.chunks[0].chunk_key)

    def test_bounds_parts(self):
        with self.assertRaisesRegex(SerializationError,'part bound'):
            serialize(fixture('long_sentence'),ChunkPolicy(max_parts=1))

    def test_bounds_mappings(self):
        with self.assertRaises(SerializationError):
            serialize(fixture('safe_link'),ChunkPolicy(max_mappings=1))

    def test_bounds_chunk_expansion(self):
        with self.assertRaisesRegex(SerializationError,'expansion'):
            serialize(fixture('long_sentence'),ChunkPolicy(max_chunks_per_node=1))

    def test_bounds_bytes(self):
        with self.assertRaisesRegex(SerializationError,'byte'):
            serialize(fixture('prose'),ChunkPolicy(max_output_bytes=1))

    def test_bounds_input(self):
        with self.assertRaisesRegex(SerializationError,'input byte'):
            serialize(fixture('prose'),ChunkPolicy(max_input_bytes=1))

    def test_bounds_membership(self):
        with self.assertRaisesRegex(SerializationError,'membership expansion'):
            serialize(fixture('small_list'),ChunkPolicy(max_memberships=1))

    def test_bounds_batch_bytes(self):
        with self.assertRaisesRegex(SerializationError,'graph byte'):
            serialize(fixture('prose'),ChunkPolicy(max_batch_bytes=1))

    def test_bad_policy_refused(self):
        with self.assertRaises(ValueError):
            ChunkPolicy(hard_max=801)

    def test_plain_text_integration(self):
        from services.structural_text_adapter import parse_structural_text
        d=fixture('prose')
        text='No markup. Café and room 2.'
        identity=d.revision.identity.model_copy(update={'source':d.revision.identity.source.model_copy(update={'source_sha256':sha256(text.encode()).hexdigest()})})
        parsed=parse_structural_text(text,identity=identity,source_format='text',fidelity='original')
        self.assertEqual(serialize(parsed).chunks[0].text,text)

    def test_tokenizer_no_network(self):
        local_tokenizer.cache_clear()
        with patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')):
            self.assertGreater(count_tokens('Hello 世界'),0)

    def test_tokenizer_missing_asset_no_fallback(self):
        local_tokenizer.cache_clear()
        with patch.dict('os.environ',{'TIKTOKEN_CACHE_DIR':str(ROOT/'nonexistent-token-cache')}):
            with self.assertRaisesRegex(SerializationError,'unavailable'):
                count_tokens('hello')
        local_tokenizer.cache_clear()

    def test_special_token_is_source_data(self):
        self.assertGreater(count_tokens('<|endoftext|>'),1)

    def test_no_application_integration_imports(self):
        path=Path(__file__).parent/'services/structural_chunking.py'
        tree=ast.parse(path.read_text(encoding='utf-8'))
        imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        self.assertEqual([x for x in imports if x and x.startswith(('database','services.'))],['services.structural_document'])
        self.assertFalse(any(x in path.read_text() for x in ('StructuralRepository','generate_embedding','requests.','httpx.')))

    def test_no_db_network_provider_needed(self):
        with patch.object(socket.socket,'connect',side_effect=AssertionError('external access forbidden')):
            self.assert_complete(serialize(fixture('safe_link')))

    def test_unchecked_input_revalidated(self):
        d=fixture('prose')
        bad=d.model_copy(update={'nodes':d.nodes+(d.nodes[-1],)})
        with self.assertRaises(ValueError):
            serialize(bad)

    def test_ledger_completeness(self):
        text=(ROOT/'docs/PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md').read_text(encoding='utf-8').split('## Phase 4.1E')[1]
        for name in ('Docling','RAGFlow','LlamaIndex','Haystack','Onyx','literal code reused: NO'):
            self.assertIn(name,text)

    def test_gold_manifest_hash(self):
        manifest=json.loads((FIXTURE.parent/'manifest.json').read_text())
        for path, expected in manifest['sha256'].items():
            self.assertEqual(sha256((ROOT/path).read_bytes()).hexdigest(),expected,path)

    def test_quarantine_boundary_excluded_not_merged(self):
        d=parse_source('# Guide\n\nSafe first.\n\nBlocked middle.\n\nSafe last.')
        q=d.revision.quality.model_copy(update={'disposition':__import__('services.structural_document',fromlist=['Disposition']).Disposition.QUARANTINE})
        nodes=tuple(n.model_copy(update={'quality':q}) if n.text=='Blocked middle.' else n for n in d.nodes)
        b=serialize(d.model_copy(update={'nodes':nodes}))
        self.assertFalse(any('Blocked middle.' in c.text for c in b.chunks))
        self.assertEqual(len([c for c in b.chunks if c.kind=='prose']),2)
        self.assert_complete(b)

    def test_navigation_exclusion_reported(self):
        b=serialize(load_gold()['navigation_near_content'])
        self.assertIn('navigation',metrics(b)['excluded_reasons'])
        self.assert_complete(b)

    def test_excluded_heading_not_reintroduced(self):
        d=parse_source('# Navigation\n\nKeep this useful body.')
        nodes=tuple(n.model_copy(update={'semantic_role':SemanticRole.NAVIGATION})
                    if n.node_type.value=='heading' else n for n in d.nodes)
        b=serialize(d.model_copy(update={'nodes':nodes}))
        self.assertFalse(any('# Navigation' in c.text for c in b.chunks))
        self.assert_complete(b)

    def test_excluded_inline_content_refused(self):
        d=fixture('safe_link')
        nodes=tuple(n.model_copy(update={'semantic_role':SemanticRole.NAVIGATION})
                    if n.attributes.link else n for n in d.nodes)
        with self.assertRaisesRegex(SerializationError,'excluded inline'):
            serialize(d.model_copy(update={'nodes':nodes}))

    def test_foreign_identity_cannot_enter(self):
        d=fixture('prose')
        n=d.nodes[-1]
        foreign=n.identity.model_copy(update={'revision':n.identity.revision.model_copy(update={
            'source':n.identity.revision.source.model_copy(update={'organization_id':99999})})})
        with self.assertRaises(ValueError):
            serialize(d.model_copy(update={'nodes':d.nodes[:-1]+(n.model_copy(update={'identity':foreign}),)}))

    def test_prompt_injection_remains_data(self):
        d=load_gold()['prompt_injection']
        b=serialize(d)
        self.assertEqual(d.nodes,b.source_graph.nodes)
        self.assert_complete(b)

    def test_inline_enumeration_atomic(self):
        d=parse_source('# Kit\n\nThe kit combines pin, case, and strap.\n\nSeparate statement.')
        b=serialize(d)
        self.assertTrue(any(n.attributes.list for n in d.nodes))
        self.assertTrue(any(c.kind=='list' for c in b.chunks))
        self.assert_complete(b)

    def test_faq_inline_list_membership(self):
        d=parse_source('# Kit\n\n## What is in the kit?\n\nThe kit combines pin, case, and strap.')
        b=serialize(d)
        self.assertTrue(any(n.attributes.list for n in d.nodes))
        for n in d.nodes:
            if n.attributes.list:
                self.assertTrue(any(n.identity in c.members for c in b.chunks))
        self.assert_complete(b)

    def test_empty_list_items_metadata_only(self):
        d=parse_source('# Layout\n\n-\n-\n')
        b=serialize(d)
        lists=[n for n in d.nodes if n.attributes.list]
        self.assertTrue(lists)
        self.assertTrue(all(n.identity in b.metadata_only_nodes for n in lists))
        self.assert_complete(b)

    def test_required_header_budget_fails_visibly(self):
        text='| '+' | '.join('Header'+str(i) for i in range(45))+' |\n| '+' | '.join('---' for _ in range(45))+' |\n'
        text+='\n'.join('| '+' | '.join('Value '+str(i) for i in range(45))+' |' for _ in range(30))
        with self.assertRaisesRegex(SerializationError,'headers exceed'):
            serialize(parse_source(text))

    def test_missing_header_not_guessed(self):
        d=load_gold()['table']
        b=serialize(d)
        self.assertEqual([n.attributes.cell for n in d.nodes if n.attributes.cell],
                         [n.attributes.cell for n in b.source_graph.nodes if n.attributes.cell])

    def test_tokenizer_corrupt_asset_refused(self):
        local_tokenizer.cache_clear()
        with patch.object(Path,'read_bytes',return_value=b'corrupt'):
            with self.assertRaisesRegex(SerializationError,'checksum'):
                count_tokens('text')
        local_tokenizer.cache_clear()

    def test_mapping_corruption_rejected(self):
        b=serialize(fixture('prose'))
        c=b.chunks[-1].model_copy(update={'text':'altered'})
        with self.assertRaises(SerializationError):
            b.model_copy(update={'chunks':b.chunks[:-1]+(c,)}).verify()


def add_gold_case(spec):
    def test(self):
        d=build(spec)
        original=d.canonical_json()
        a,b=serialize(d),serialize(d)
        self.assert_complete(a)
        self.assertEqual(a.canonical_json(),b.canonical_json())
        self.assertEqual(a.canonical_hash(),b.canonical_hash())
        self.assertEqual(original,d.canonical_json())
        self.assertEqual(any(c.part_count>1 for c in a.chunks),spec['multipart'])
        for c in a.chunks:
            if c.kind!='prose':
                self.assertFalse(any(m.usage=='overlap' for m in c.mappings))
    setattr(ChunkContracts,'test_gold_'+spec['name'],test)


for _spec in specs():
    add_gold_case(_spec)


def add_witness(name):
    def test(self):
        d=load_gold()[name]
        b=serialize(d)
        self.assert_complete(b)
        self.assertEqual(d.canonical_json(),b.source_graph.canonical_json())
    setattr(ChunkContracts,'test_witness_'+name,test)


for _name in load_gold():
    add_witness(_name)


class DoclingChunkIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from scripts.evaluate_structural_docling_adapter import FIXTURES, identity
        from services.structural_docling_adapter import extract_artifact, map_extraction
        cls.batches={}
        for name in ('workshop.pdf','merged.pdf','workshop.docx'):
            data=(FIXTURES/name).read_bytes()
            config=dict(identity=identity(data),source_format=name.rsplit('.',1)[1],fidelity='original')
            record=extract_artifact(data,model_cache=ROOT/'.codex_structural_4_1d/models',**config)
            doc=map_extraction(record,artifact=data,**config)
            cls.batches[name]=serialize(doc)

    def test_pdf(self):
        b=self.batches['workshop.pdf']
        self.assertEqual(metrics(b)['unaccounted_bytes'],0)
        self.assertEqual(metrics(b)['cells'],{'expected':6,'retained':6})

    def test_docx(self):
        b=self.batches['workshop.docx']
        self.assertEqual(metrics(b)['unaccounted_bytes'],0)
        self.assertEqual(metrics(b)['cells'],{'expected':9,'retained':9})

    def test_merged_header_not_invented(self):
        b=self.batches['merged.pdf']
        access=[n for n in b.source_graph.nodes if n.text=='Access']
        self.assertTrue(access)
        self.assertFalse(any(n.attributes.cell.is_header for n in access))
        self.assertEqual(metrics(b)['unaccounted_bytes'],0)

    def test_merged_span_preserved(self):
        b=self.batches['merged.pdf']
        self.assertTrue(any(n.attributes.cell and n.attributes.cell.column_span==2 for n in b.source_graph.nodes))
        self.assertTrue(b.verify())

    def test_repeated_serialization(self):
        for b in self.batches.values():
            self.assertEqual(b.canonical_hash(),serialize(b.source_graph).canonical_hash())


if __name__=='__main__':
    unittest.main()
