# Hybrid RAG core through Phase 3.7

This is the maintenance summary for the accepted implementation. It is not a production deployment record. Historical execution reports and raw acceptance traces are retained locally, not required at runtime.

## Ownership and safety boundaries

- Authenticated/public routes keep their existing authorization and session rules; they pass the bound conversation ID to the shared answer path.
- `knowledge_scope.py` owns organization, bot, READY/completed, active crawl/version and embedding-profile eligibility. Every recall, hydration, field and sibling path remains within that boundary.
- `HardKnowledgeScope` is database-owned. Planner suggestions and resource candidates are soft relevance hints; only complete, uniquely corroborated identities can narrow scope. An incomplete comparison keeps unresolved members visible.
- Resource catalog descriptors contain bounded metadata, not arbitrary source instructions. Resource search validates authorized source anchors and versions before exposing names or navigation.
- Cache identities include contract, corpus and hybrid configuration. Retrieval cache hits revalidate current knowledge eligibility.
- Missing selected evidence is not proof of catalog absence. Provider/retrieval/context failures have technical terminals, not fabricated business answers.

## Retrieval and evidence

`rag_service.py` composes independent dense and lexical recall, document-first field evidence, bounded sibling expansion and reservation-aware selection. FTS uses parameterized PostgreSQL `websearch_to_tsquery` / `ts_rank_cd` with ranking before LIMIT. Weighted RRF combines one-based channel ranks, not incomparable raw scores.

Resource discovery uses bounded exact, FTS, trigram and metadata channels. RapidFuzz corroborates only their bounded candidate union; ambiguity and numerical conflicts cannot be resolved by selecting a semantic score winner.

The canonical selection policy reserves resource/field obligations and complete ordered evidence bundles before optional depth. Whole field paragraphs, source identity and compatibility conditions survive review and bounded context admission. Monetary records retain source/role provenance; unknown amounts are not promoted to verified prices. Static knowledge cannot certify live inventory.

The planner/reviewer use the bot's existing provider and encrypted credential architecture. Auxiliary work has bounded worker capacity and separate setup, inference and cleanup deadlines. Structured reviewer output is schema/reference validated; invalid output retains deterministic evidence. Source links are restricted to admitted source identities. See the root `OPEN_SOURCE_ADAPTATION_NOTES_PHASE_*.md` ledgers for design attribution and deliberately deferred features.

## Rollout configuration (unchanged)

- `RAG_LEXICAL_BACKEND`: default `legacy`; `postgres_fts` selects Phase 2 FTS.
- `RAG_DENSE_WEIGHT=1`, `RAG_FTS_WEIGHT=1`, `RAG_RRF_K=60`, `RAG_CANDIDATE_CEILING=500` are the existing defaults.
- `RAG_RESOURCE_DISCOVERY`: default `off`; explicit `on` enables catalog discovery after migration and authorized projection.
- No catalog is automatically backfilled on startup/chat. `ResourceCatalogProjector.project` is an explicit, tenant/bot-scoped, caller-transaction-owned batch (maximum 256 source documents).

No environment values are changed by this checkpoint. Code inclusion does not imply these rollout switches are enabled in an existing deployment.

## Generation model default

New Gemini bots and Gemini generation with no explicit model use `models/gemini-3.5-flash-lite`. Explicit bot models are preserved; previously selectable Gemini models remain selectable. OpenAI, Claude and Grok choices are unchanged. Existing explicit auxiliary-model configuration is preserved; verification continues to use the bot's generation model.

No stored bot is migrated by changing the default. The historical legacy-column backfill remains unchanged. Gemini embedding stays `gemini-embedding-001`, OpenAI embedding stays `text-embedding-3-small`, and the existing profile/dimensions remain unchanged.

## Database prerequisites and release order

The forward chain extends `20260903_01` -> `20260910_01` (chunk English FTS GIN) -> `20260912_01` (resource catalog, tenant-qualified keys, revision triggers and resource indexes).

For a separately authorized deployment, run the existing one-off release command from `backend`: `python -m alembic -c alembic.ini upgrade head`, then start API/worker replicas. Production API startup verifies revision currency; it does not independently migrate each replica. The FTS migration uses concurrent index creation. Resource projection/backfill is separate from migration and needs explicit operational authorization. This checkpoint runs no production migration or projection.

FTS downgrade removes its own index. Catalog downgrade removes the catalog-owned objects/constraints and retains the shared extension; do not use downgrade as an unreviewed data rollback. No customer document/chunk/embedding rewrite is part of these upgrades.

## Validation and limitations

From `backend`, run `.\.venv\Scripts\python.exe -B -W ignore::DeprecationWarning scripts/test_scoped_rag_regressions.py`. It blocks configured application DB access and live HTTP. Focused model-default coverage lives in `test_generation_model_defaults.py`.

Reusable PostgreSQL acceptance/benchmark harnesses under `backend/scripts` are permanent test infrastructure, not runtime startup tasks. Remote modes require explicit opt-in, disposable-database guards and owned-schema cleanup. Never point them at an application/customer database. Real PostgreSQL validation must be separately authorized; offline tests do not establish live provider availability, production latency or current deployment health.

Phase 4 is not implemented by this checkpoint. Resource-level dense population, automatic projection and later semantic optimizer work remain separate decisions.
