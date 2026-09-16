# STRUCTURAL_GOLD_V1

Frozen hand annotations for structural contracts, not chatbot answer GOLD and
not output from an implemented extraction adapter. All examples load offline.

`real_sources.json` contains 11 short, exact excerpts from the already saved
`SOURCE_PRODUCTION_SNAPSHOT.json`. Only public source text, source URL, document
ID/version, source/excerpt SHA-256 and UTF-8 excerpt start are retained. No
crawler metadata, credentials, vectors, answers or benchmark grades are copied.
Fixtures use a synthetic org/bot identity (70001/70002); document numbers are
test data, not runtime rules. Referenced product roots are explicit hand
annotations of saved identities, not URL resolution performed by the loader.

`synthetic_sources.json` contains eight non-commerce examples and 11 adversarial
examples. The long list item and table cell are deliberate source strings, not
generated embedding chunks. Source content is inert data.

`manifest.json` freezes each normalized document's canonical SHA-256 and both
source files' SHA-256 (file CRLF normalized to LF for cross-platform checkouts).
Tests never rewrite these hashes. Changing GOLD requires a reviewed new version;
do not regenerate hashes to make a failing adapter pass.

## Annotation convention

- Annotation start/end are half-open **Unicode character** indices into the
  bundled excerpt. The fixture-only loader verifies exact slices and converts
  them to UTF-8 offsets in the immutable full source, using `source_start`.
- Source spans in the contracts are always explicitly typed; no enriched token
  offset is reused. Missing location has an explicit reason.
- Empty containers have a whole-excerpt provenance span. Their keys use the
  explicit annotation label/path and occurrence, not text alone.
- Nodes are manually identified, ordered and parented. No Markdown recognition,
  source-quality detector, relationship inference or full-corpus parsing occurs.
- The three complete ingredient/source lists annotate enumerations in the
  source's lead prose. They are not inferred from shorter ingredient-card lists.
- Review and timeline groups retain exact source blocks as well as explicitly
  mapped children; these annotations do not prescribe chunk duplication.
- Resveratrol's concatenated `$55.20`/`$44.16` amounts do **not** prove regular,
  sale, subscription or one-time roles for each amount, or an ISO currency.
  Full offer labels remain in the parent block; these amount roles/currencies
  stay unknown. Synthetic software-plan data exercises an explicit role.
- The blocked-tail witness has block quality `blocked`, but document quality
  `mixed/manual_review`. No existing page is quarantined or altered.

## Metric interpretation

`services.structural_metrics` compares source-pinned normalized objects using
stable keys, parent membership and explicit edges. Missing/wrong edges count
against recall/precision respectively. Empty denominators return `None` (N/A),
not a perfect score. Cross-source comparisons fail closed.

An adapter using different parser paths will need explicit gold alignment in a
later phase. This module does not use semantic/text similarity to guess it.
Provenance completeness reports located text-node coverage separately from
faithful preservation of an honest unavailable marker.

Serialization coverage measures the union of **asserted mapping byte ranges**,
not rendered text fidelity or token limits. GOLD has no generated chunks or
mappings; dedicated synthetic mapping tests exercise gaps and overlaps. Actual
serializer reconstruction, 800-token limits and extraction accuracy remain
future gates. Collection-edge metric has no collection-positive gold fixture;
its empty denominator is N/A, not evidence of extraction success.

The existing REAL_CORPUS_V1_EVAL_V1, its answers and its grades remain separate
and untouched.
