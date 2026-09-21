# Upstream and integration test mapping

Pin: v0.27.2 / a024bea0cd93f39e6652a42bf84dd20c55bc560b. Exact source/destination hashes and attribution are in the port manifest. All testing described here was provider-free.

## Ported tests

| Pinned upstream test | Ported destination | Component / adaptations | Result |
| --- | --- | --- | --- |
| test/unit_test/deepdoc/parser/test_txt_parser.py | backend/tests_ragflow/test_upstream_txt.py | Exact delimiter/paragraph merge assertions; namespace imports only | PASS |
| test/unit_test/deepdoc/parser/test_markdown_parser.py | backend/tests_ragflow/test_upstream_markdown.py | Fences, tables, heading delimiters, duplicate table protection; isolated imports | PASS |
| test/unit_test/deepdoc/parser/test_html_parser.py | backend/tests_ragflow/test_upstream_html.py | Text preservation/merge/bodyless HTML plus original shared HTML semantics fixture; injected tokenizer | PASS |
| test/unit_test/rag/nlp/test_search_rerank.py | backend/tests_ragflow/test_upstream_rerank.py | All three rerank token-assembly paths, question tokens/missing fields; namespace isolation | PASS |
| internal/parser/parser/testdata/unified_html_cases.json | backend/tests_ragflow/upstream_html_cases.json | Exact shared upstream expected HTML results | PASS |

Combined: **47/47 ported upstream tests pass**. The original rerank unit tests intentionally bypass constructor and stub queryer to isolate token assembly; new engine tests separately execute the actual FulltextQueryer/Dealer pipeline. These unit assertions do not validate native SDK tokenization or real ES ranking.

## New integration and safety tests

**63/63 new tests pass** (59 engine tests including minimum-budget and partial-delete failure checks, 4 platform boundary tests). Total **110/110**, one existing Starlette/anyio deprecation warning.

Coverage includes:

- Ingest: text, Markdown headings/lists/tables/fences, HTML/crawl, product-like neutral fixtures, long/tiny inputs, duplicate text with distinct IDs, plain PDF, ordered DOCX paragraphs/table.
- Pipeline: actual upstream parse/merge/query/rerank/context code with explicit deterministic tokenizer/vectors and test-only memory index. Exact, semantic-shaped, lexical, category, comparison, multi-document, attribute, follow-up, exclusion and catalog inputs exercise contract execution; this is NOT measured quality for those intent classes.
- Security: stronger foreign org/bot matches, unauthorized source/doc narrowing, wrong source version, generation/profile, non-ready source, revoked authority, forged backend rows, corrupted text, malformed IDs and same content across identities.
- Ingestion lifecycle: immutable source digest, new-version update, source delete, partial indexing readiness, atomic ES manifest claim.
- Rerank: order, ties, missing-required reranker, explicit failures and invalid numeric outputs.
- Context: whole exact evidence, full-identity deduplication, deterministic order/citations, byte/token/unit caps including empty context with a one-byte budget.
- ES: actual elasticsearch-dsl request construction, mandatory scope filters inside KNN and lexical query, pinned lexical gating, caller condition nonmutation. Native ES server is not mocked as if accepted.
- Application: current adapter forwards unchanged, actual old service import, actual main import with DB initialization explicitly stubbed, default=current, production selection denied, optional FastAPI HTTP authentication/tenant rejection, response shape, same system instruction/bot/history delivered to mocked existing generation.
- Future comparison interface: one generic synthetic contract test; no benchmark question set or labels.

tests_ragflow/conftest.py blocks outbound socket connections, except the exact stdlib Windows asyncio socketpair construction call. Token counting is deterministic in offline tests, avoiding asset downloads. No environment credentials are inspected.

## Commands / limitations

From backend:

```powershell
..\.codex_ragflow_venv\Scripts\python.exe -B -m pytest tests_ragflow -q --tb=short -p no:cacheprovider
..\.codex_ragflow_venv\Scripts\python.exe -B scripts/ragflow_local_smoke.py
```

Smoke result: ingest PASS, retrieval PASS, context PASS, citations 3, provider_calls 0; explicitly synthetic fixture mode.

The established safe canonical suite was run once using the unchanged backend environment:

```powershell
.\.venv\Scripts\python.exe -B -W ignore::DeprecationWarning scripts/test_scoped_rag_regressions.py
```

Result: **3945/3948 PASS**, 3 failures, 459.886 seconds. Failures:

1. test_structural_retrieval_headings.SafetyTests.test_all_previous_hashes (line 221)
2. test_structural_retrieval_entries.ContractTests.test_previous_frozen_snapshot (line 225)
3. test_structural_resource_descriptors.SafetyTests.test_local_preservation_when_artifacts_present (line 297)

All expect old rag_planning.py hash b90cab62a66f27c05f1576810c3ebe79e94d1c6a6d92d037bccc0780186c4f90. Actual c643ccdcad43b573768d4500e7fd56f633dc861efee93337c8bcb304190f03e6 equals the pre-task preservation snapshot. These are pre-existing stale-hash assertions, not changed implementation. They were not edited, bypassed or represented as passing.

No real ES/tokenizer/model integration, retrieval benchmark, GOLD scoring, live chatbot or provider calls ran. Native service, model and large-corpus performance/security acceptance is still required before production.
