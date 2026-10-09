"""Input, source provenance and artifact isolation checks without model loading."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from retrieval_engine.config import RetrievalConfig
from retrieval_engine.retrieval import LocalRetrievalEngine


class RetrievalContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.config = RetrievalConfig(root=Path(self.temporary.name))
        self.engine = LocalRetrievalEngine(self.config)

    def write_corpus(self, records):
        self.config.corpus_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.corpus_path.write_text(
            "\n".join(json.dumps(record) for record in records), encoding="utf-8"
        )

    def document(self, **changes):
        return {
            "id": "document-1",
            "source_id": "source-1",
            "title": "Product instructions",
            "url": "https://example.com/product",
            "text": "Keep the package dry.",
            **changes,
        }

    def test_blank_and_unbounded_questions_fail_before_loading(self):
        for question in ("", "  ", None, "x" * 2001):
            with self.subTest(question_length=len(question) if question is not None else None):
                with self.assertRaises(ValueError):
                    self.engine.retrieve(question)
        self.assertEqual(self.engine.status()["state"], "not_loaded")

    def test_valid_question_does_not_implicitly_download_or_load_models(self):
        with self.assertRaisesRegex(RuntimeError, "has not been loaded"):
            self.engine.retrieve("How should I store the product?")
        self.assertFalse(self.config.models_path.exists())

    def test_corpus_must_not_have_duplicate_document_ids(self):
        self.write_corpus([self.document(), self.document(text="Another paragraph.")])
        with self.assertRaisesRegex(ValueError, "Duplicate corpus document"):
            self.engine._load_corpus()

    def test_distinct_documents_cannot_silently_overwrite_source_identity(self):
        self.write_corpus([self.document(),self.document(id='document-2',text='Conflicting source.')])
        with self.assertRaisesRegex(ValueError,'Duplicate corpus source_id'):
            self.engine._load_corpus()

    def test_another_dataset_uses_explicit_paths_and_same_local_models(self):
        alternate=replace(self.config,corpus_file=Path(self.temporary.name)/'other'/'dataset.jsonl',
                          index_directory=Path(self.temporary.name)/'other-index')
        self.assertNotEqual(alternate.corpus_path,self.config.corpus_path)
        self.assertNotEqual(alternate.index_root,self.config.index_root)
        self.assertEqual(alternate.models_path,self.config.models_path)

    def test_empty_or_missing_source_fields_are_rejected(self):
        for field in ("id", "source_id", "title", "text", "url"):
            with self.subTest(field=field):
                self.write_corpus([self.document(**{field: ""})])
                with self.assertRaises(ValueError):
                    self.engine._load_corpus()

    def test_citation_urls_cannot_inject_a_script_or_local_file(self):
        for url in ("javascript:alert(1)", "file:///C:/private.txt", "https:///no-host",
                    "https://user:secret@example.com/data", "https://example.com/\npath"):
            with self.subTest(url=url):
                self.write_corpus([self.document(url=url)])
                with self.assertRaisesRegex(ValueError, "unsafe source URL"):
                    self.engine._load_corpus()

    def test_original_unicode_and_whitespace_are_preserved(self):
        text = "Safety — read first.\n\n  Keep dry; avoid heat.\n"
        self.write_corpus([self.document(text=text)])
        self.assertEqual(self.engine._load_corpus()[0]["text"], text)

    def test_pipeline_fingerprint_inputs_change_with_ranking_configuration(self):
        smaller = LocalRetrievalEngine(replace(self.config, rerank_candidates=16))
        self.assertNotEqual(self.engine.pipeline_provenance(), smaller.pipeline_provenance())
        self.assertEqual(self.engine.pipeline_provenance()["generated_queries"], 0)
        self.assertEqual(self.engine.status()["models"]["generative_llm"], "disabled")

    def test_impossible_model_window_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "special tokens"):
            replace(self.config, chunk_tokens=480, max_query_tokens=96)


if __name__ == "__main__":
    unittest.main()
