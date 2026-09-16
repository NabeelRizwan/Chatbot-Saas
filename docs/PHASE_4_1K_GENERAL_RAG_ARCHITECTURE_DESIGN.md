# Phase 4.1K — general source capture and retrieval representation

Research 2026-09-16; finalized 2026-09-17 (Asia/Calcutta) · **PHASE 4.1K DESIGN — COMPLETE** · Design/research only

Two independent decisions:

- **Source capture: C — another design:** an immutable, privacy-minimized inert
  replay artifact plus a bounded, source-pinned structural sidecar. Do not retain
  unrestricted raw website HTML. Record the original content hash separately
  from the retained artifact hash and explicitly record fidelity losses.
- **Retrieval representation: B — contextual dense entries + atomic PostgreSQL
  FTS + bounded structural expansion.** Search representations route to exact
  evidence; they do not replace it or confer subject identity.
- **Order: general retrieval-entry implementation first**, as an offline-only
  contract/serializer/evaluator. Source-capture enrichment follows separately;
  it cannot recover anchors or resource boundaries absent from historical data.

Everything described as a proposed field, budget, index, state, algorithm or
transaction below is **not implemented or enabled**. No production acceptance,
recall gain, provider-token saving or activation readiness is claimed.

## 1. Phase J checkpoint SHA

Audited J and created local checkpoint
`95cd002c77a0b50b4eac57500063a5034de2e8db`:
`Phase 4.1J: add source-pinned resource boundary descriptor study`.
Parent I: `76c142ffb14f0a591a7dcd271adff70abf6483d5`.

Exactly the ten J files identified in its report were committed: three offline
descriptor/corpus/evaluator scripts, focused tests, three GOLD JSON files,
canonical test-runner registration, OSS ledger and J report. No runtime service,
live catalog, database path, provider/embedding path or ignored result payload
was staged. J audit: **684/684 preservation hashes**, secret scan, AST and
staged whitespace checks passed. Accepted prior results: **108/108 J,
892/892 structural A–I, 3,083/3,083 canonical backend**; not rerun in K.
Working tree was clean immediately after the local J checkpoint. Nothing pushed.

K changes only this design and the OSS ledger. A small ignored calculation
helper reads frozen files and computes arithmetic envelopes; it does not create
retrieval entries or alter the structural graph. K remains uncommitted.

## 2. OSS source study

The [implementation ledger](PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md#phase-41k--source-capture-and-three-layer-retrieval-design-2026-09-16)
records source/function, exact pin, license, copied/adapted status, keep/reject
decisions and reasons. Actual current implementation and license files were read,
not just documentation. No upstream implementation was copied or executed.

| Repository | Current source pin | License of inspected source | Architectural evidence |
| --- | --- | --- | --- |
| Docling Core | `cc39622c6a4bb2643a8631edd996d8874a8e6a47` | MIT | Items and heading metadata survive separately from embedding-targeted contextualization; peers are budgeted using contextualized tokens. |
| Docling | `d4fa979af44a878700f8576eaba7e27dd9330005` | MIT | HTML IDs and scoped hyperlinks can be read before projection; generated internal element IDs are not proof of original anchors. |
| LlamaIndex | `fd4a517ad6490f0c8464a13fdf133760b696434a` | MIT | Hierarchy creation, leaf selection and later parent retrieval are distinct operations. |
| Haystack | `95458a7dc7c59a4d0a46567b674b6a772062ffe3` | Apache-2.0 | Root/intermediate/leaf splits and later source-position windows are different representations. |
| RAGFlow | `7bc159d64e565d7fa93cd56b866772dad66edf31` | Apache-2.0 | Searchable children, stored parents, title/keyword fields and parent lookup coexist. |
| Onyx | `c564d334dd2635471947e5d3a5a1eca3f2d808af` | MIT Expat outside EE | Source sections, processed sections, contextual search chunks and embeddings have separate contracts. |

Relevant defaults are not universal optimal sizes: LlamaIndex's hierarchy uses
2048/512/128; Haystack's ordinary splitter defaults to 200 **words**, with
sentence windows defaulting to three neighboring splits each side. Docling's
budget comes from its tokenizer configuration. RAGFlow has an absent-config
512-token default but several 128-token fallbacks. Onyx subtracts title,
metadata and optional generated context from a configurable content budget.
These support explicit budget accounting, not adopting another model's limit.
See the pinned [LlamaIndex implementation](https://github.com/run-llama/llama_index/blob/fd4a517ad6490f0c8464a13fdf133760b696434a/llama-index-core/llama_index/core/node_parser/relational/hierarchical.py),
[Haystack splitter](https://github.com/deepset-ai/haystack/blob/95458a7dc7c59a4d0a46567b674b6a772062ffe3/haystack/components/preprocessors/document_splitter.py),
[Docling HybridChunker](https://github.com/docling-project/docling-core/blob/cc39622c6a4bb2643a8631edd996d8874a8e6a47/docling_core/transforms/chunker/hybrid_chunker.py),
[RAGFlow chunker](https://github.com/infiniflow/ragflow/blob/7bc159d64e565d7fa93cd56b866772dad66edf31/rag/app/naive.py)
and [Onyx Chunker](https://github.com/onyx-dot-app/onyx/blob/c564d334dd2635471947e5d3a5a1eca3f2d808af/backend/onyx/indexing/chunker.py).

Local compatibility was checked against `HardKnowledgeScope`, `ready_chunks`,
rank-only `weighted_rrf`, immutable structural contracts, J's native corpus
loader and G's publication design. None is changed. In particular, current
`ready_chunks` does not distinguish two simultaneously READY representation
generations; K does not authorize inserting a second live representation.

## 3. Multi-tenant invariants

Trusted server-owned identity accompanies every object, mapping, lookup and
cache entry: organization, bot, source/document, source version and hash,
crawl ID/version where applicable, capture-policy/version, structural revision,
representation-policy/version and embedding-profile identity where applicable.
Null crawl means a validated upload, not a wildcard. `None` and empty authorized
sets retain their existing distinct meanings.

`HardKnowledgeScope` remains authoritative. Resource relationships, identical
text, URLs, headings, structured data, parser metadata and model output cannot
assign ownership or widen it. Composite foreign-key/check constraints and
repository predicates must eventually enforce the complete identity, not merely
an unscoped child ID. Hashes serve integrity; text hashes are not authorization.

The future serving manifest must pin one active document/source generation and
compatible graph, atomic index and dense representation. READY, completed
processing, active crawl/version, nondeleted state and profile compatibility
apply in both retrieval channels, expansion, evidence assembly and citations.
Recheck scope when materializing hits and following edges; do not retrieve a
global unfiltered candidate pool and rely only on a final filter.

Cross-document edges require independent authorization of both endpoints and
their exact active versions. No automatic cross-bot edge, even within one org.
Names, link targets, resource metadata and existence must not leak through
errors, counts, diagnostic traces or cache hits. Two bots with identical bytes
have distinct authorization identities, mappings, indexes and cache namespaces.

Future cache identity includes HardKnowledgeScope identity, serving-generation
epoch, source/crawl/revision manifest digest, representation/lexical policy,
embedding profile, query contract, resolved resources and authorized conversation
state. Invalidation on refresh, deletion, access change or publication is
mandatory; stale cached evidence is revalidated before delivery. This is a
required future extension, not a claim that today's cache implements it.

## 4. J conclusions

J preserved the source graph and evidence mappings. Automatic descriptors could
not invent missing source declarations: 86 review groups remained unresolved,
147 linked-heading candidates were not proven cards, and no single-resource
root inventory was proven. Of 1,469 link nodes, 110 had exact base targets,
461 lacked declared fragment targets and 898 lacked registered base targets.
Two manually asserted FAQ boundaries identified six candidates but did not make
their proposed packing safe.

The decisive packing result is independent of capture enrichment: all 46
identity-blocked peers still fail unchanged rules even with hypothetical correct
identity: **26 typed attributes, 12 typed containers, 8 qualifications**.
I/J's 3,230 candidates are evaluation observations, not a desired future count.
The historical absolute review threshold is retired as a success criterion.
Do not weaken H/I/J evidence rules to lower vector count.

## 5. Source-capture problem

Historical extracted Markdown preserves useful content but not a complete DOM,
literal anchor inventory, link-owner blocks, structured assertions or resource
inventory. A heading called Reviews does not prove a `#reviews` anchor; a nearby
product link does not prove review ownership. No later parser or model can
restore missing authoritative declarations from those bytes.

General lifecycle:

`fetched bytes (transient) -> admitted immutable source version -> bounded structural sidecar -> parser revision -> graph/atoms/search representations`

Capture fidelity and representation efficiency are separate problems. Better
capture helps attribution and replay; it does not make evidence units freely
mergeable or prove that every page describes one business entity.

## 6. Source-capture architecture options

| Option | Replay / future parser compatibility | Fidelity / debugging | Security, privacy and cost | Decision |
| --- | --- | --- | --- | --- |
| A. Full raw HTML only | Broadest byte replay | Declarations recoverable, ownership must be reparsed each time | May retain scripts, tokens, personal/session data; repeated parse cost; no bounded query sidecar | Reject as default and as sole artifact. |
| B. Sanitized inert HTML only | Reparse retained markup; cannot recover removed fields | Good retained anchors, but sanitizer can erase boundaries without a loss manifest | Safer, but no prevalidated bounded registry or provenance lookup | Insufficient alone. |
| C. Normalized sidecar only | Limited to the first extractor's schema and mistakes | Efficient explicit mappings; future parser cannot revisit lost markup | Smallest retained attack/data surface; difficult forensic replay | Reject as the general sole source. |
| D. Immutable raw artifact + bounded sidecar | Broadest replay plus efficient graph inputs | Best original-byte debugging if admissible | Stores forbidden secrets unless an additional admission/minimization policy intervenes; highest retention burden | Reject unrestricted raw retention. |
| Selected variant: immutable privacy-minimized inert artifact + bounded sidecar | Replay retained, policy-admitted source with independent parser versions | Explicit original/retained hashes, loss manifest, preserved admissible anchors/ownership | More privacy control than D; more replay than C; deliberate fidelity loss | **Choose this single architecture (decision C: another design).** |

All options require tenant-scoped storage, retention and deletion. Compression
does not sanitize data. More retained data is not automatically better.

## 7. Recommended source artifact

One immutable capture manifest references two independently hashed objects:
an inert replay artifact and a bounded normalized sidecar. Proposed fields:

- Trusted scope and source/crawl/capture identities; server-observed UTC fetch
  time; claimed source-modified time separately labeled and validated, never
  used as a security/version authority.
- Original fetched-content SHA-256, retained-artifact SHA-256, MIME/encoding,
  decoded byte counts, capture/minimization policy versions and source fidelity.
  Hash original bytes transiently before redaction; never mislabel retained
  bytes as original raw HTML.
- Approved final/canonical page URL and safe base identity; canonical tags are
  source assertions, not permission to fetch or to reassign document identity.
- Exact retained element/attribute/text spans, capture-time element occurrences,
  structural paths, heading tree, block/list/table ownership and safe links.
- Original-to-retained provenance where available; redaction/omission reason
  codes and spans, not removed values. Normalized text points to retained bytes.
- Sidecar schema/hash, parser-independent capture declarations, component
  counts and explicit completeness/truncation/rejection states.

Capture element IDs identify occurrences within a pinned artifact. Keep literal
HTML IDs separately. DOM paths are addresses within that version, not stable
identity across edits. Store root-resource inventory only when actually captured
and complete; otherwise UNRESOLVED, not an inferred single-resource page.

No database/storage implementation or public download endpoint is added in K.
Artifacts must eventually be private, encrypted at rest, server-authorized,
never publicly rendered, and subject to org deletion/retention policy.

## 8. Security and privacy

Admission/minimization happens **before durable storage, logs or tracing**.
Discard unrestricted raw buffers afterward. Fail closed on unsafe/unclassifiable
payloads; do not save a plaintext rejected-payload quarantine as a workaround.

| Surface | Required future rule |
| --- | --- |
| Browser/script/network | No browser execution during replay, no script/eval/event handler, stylesheet execution, remote images, iframe, embedded object or external resource loads. HTML is parsed as data, never served inline. Replay runs with network denied and low OS privileges. |
| Cookies/auth/session | Never capture headers, cookies, session stores, localStorage, form inputs/hidden fields/values/actions, checkout/bootstrap/session state or authenticated browser dumps. Never persist credential-bearing URLs; no auth-bearing source request is included in the artifact. |
| URLs and attributes | Strict allowlist of content structure, inert text and safe structural attributes (`id`, eligible anchor `name`, heading level, list order, table spans). URL schemes limited to approved HTTP(S)/relative/fragment data; reject userinfo, executable/data/file schemes and sensitive query/path values. No arbitrary `data-*`, style, event, nonce or token attributes. |
| Metadata | Allow trusted manifest fields, validated MIME/encoding/language, safe title/timestamps, provenance, hashes and bounded structural records. Deny transport headers, credentials, authorization/ownership overrides, session IDs, form state, checkout/payment state, browser storage and arbitrary source metadata passthrough. Source assertions live in a separate non-authoritative namespace. |
| JSON-LD | Only bounded `application/ld+json` data extracted inertly before script removal; no evaluation or remote context fetch. Apply the same privacy admission to every scalar and URL. Other script contents are never retained. |
| XML/binaries/archives | Disable DTD/entity expansion and external relationships. No macros, active PDF actions/JavaScript, executables or embedded attachments. DOCX containers need bounded member/count/ratio/decompressed-byte checks, path-traversal protection and format admission; no automatic recursive archive extraction. |
| Prompt injection | Source text is quoted evidence only; no tools, prompts, routing rules, ownership, executable references or expansion commands can be set by it. Exact text can retain hostile prose as untrusted content, never instructions. |

Proposed initial admission bounds: 8 MiB transfer /16 MiB decoded HTML, depth
128, 100,000 elements, 20,000 links and 20,000 anchors per artifact; sidecar
16 MiB maximum. These are future review values, not configuration changes.
Exceeding a bound is a visible failure/incomplete-capture state, never a complete
resource inventory. Large files need bounded page/part manifests and aggregate
quotas; unlimited corpus size does not mean unlimited single-object parsing.

Minimization by construction prevents retention of known credential channels.
No scanner can prove that arbitrary public prose contains no secret or personal
data. Suspect values must be refused/redacted; implementation needs adversarial
privacy tests and a reviewed retention policy before release. We do **not**
claim absolute content-secret detection from an HTML sanitizer.

## 9. Anchor registry

Key each declaration by full scope, source/capture version/hash, approved page
identity, literal `id` or eligible `<a name>` value and occurrence. Map to capture
element, retained span, then zero or more nodes in a particular structural
revision. Preserve declaration type and provenance.

Only actual captured declarations prove targets. Generated element IDs, inferred
heading slugs and parser-added names cannot enter the declaration namespace.
Fragment decoding/URL resolution is deterministic, bounded and versioned; no
case-folding or fuzzy match of fragment text. Duplicate declarations remain
AMBIGUOUS rather than selecting the first. Missing, redacted, unmapped, unsafe,
stale and unsupported text-fragment targets have explicit states.

Resolution is against an authorized pinned target version. A refreshed page may
lose its anchor; do not reuse yesterday's resolved edge. A same-document `#x`
does not require a network fetch. Historical Markdown's missing registry remains
missing; capture enrichment requires newly authorized source acquisition.

## 10. Link ownership

Each retained link record carries exact source/version, element/text node,
owner block occurrence and interval, original admitted href, approved base,
resolved safe base, fragment, scheme status and target-resolution state.
Original href is retained only if safe; otherwise retain a hash/reason, not a
secret-bearing value. Do not imply that a redacted link is exactly resolvable.

Ownership comes from actual containment/typed source declaration, never nearest
heading, visual proximity or a preceding review. A link in navigation is owned
by navigation. A review's own reference can support a bounded relation only if
both ownership and target are proven. Base-tag/canonical/redirect observations
remain separate; they never trigger replay fetches or expand crawl/tenant scope.

Target states include exact document, exact declared anchor, unresolved base,
unresolved fragment, ambiguous, stale, unsafe and redacted. Linking to another
customer's page must not disclose whether that page is indexed elsewhere.

## 11. Resource-block provenance

Generic descriptors identify block interval, structural type, source assertion,
owner references, node members, nested boundaries and completeness. A card may
describe a product, room, plan, service or course without a domain-specific
runtime branch. A list of links is not automatically a resource inventory.

Separate structural CONTAINS, navigational REFERS_TO, source-asserted DESCRIBES
and derived relevance. Root-resource assignment requires its own complete,
source-backed inventory. Conflicting/nested/multiple resources stay distinct;
unknown identity is not equal identity. Capture can provide better evidence for
future descriptors without changing J's identity or H's evidence packing rules.

## 12. Structured-data policy

Proposed limits: eight JSON-LD blocks, 256 KiB total admitted JSON, depth 16,
10,000 nodes/properties and 8 KiB per scalar. Duplicate keys, excessive nesting,
invalid/nonfinite values and over-limit data are rejected explicitly. No
remote `@context`, imports or executable interpretation; bounded local graph
references are cycle-checked.

Retain inert `@id`, `@type`, local references and bounded scalar assertions as
predicate/value/source-span tuples. Generic property names are data, not
application fields; unknown vocabularies remain uninterpreted. Only validated
safe URIs and privacy-admitted values survive. Do not deserialize source keys
into runtime models, authorization fields, model settings or tool instructions.

Pin each assertion to script occurrence, source/capture hash and span. Keep
contradictions between JSON-LD, visible text and other assertions visible with
their separate origins. An ItemList or Review assertion alone neither proves
DOM ownership nor guarantees truth, current price, whole-page identity or a
complete catalog. A later adapter may propose a relation, subject to exact
scope/provenance validation and explicit conflict policy.

## 13. Source versioning

Separate: source fetch/content version; privacy/capture-policy version; retained
artifact hash; normalized-sidecar schema; parser implementation/config revision;
structural revision; entry policy/tokenizer revision; embedding profile; serving
generation. Parser upgrades do not fabricate a new fetch time or crawl.

An unchanged content hash can reuse a tenant-owned admissible artifact but still
has explicit fetch/crawl provenance. No cross-tenant hash-keyed identity reuse.
Changed minimization policy creates a new retained representation, not an
overwrite of old bytes. Relationships and caches never float across versions.
Publication/deletion must eventually follow G's scoped atomic manifest/CAS and
rollback requirements, not merely mark new children READY.

## 14. Parser replay without recrawl

Replay verifies tenant authorization, retention rights, hashes, MIME and capture
fidelity; reads an immutable artifact in a network-denied sandbox; creates a new
candidate sidecar/structural revision; validates mappings and completeness; and
stops before activation. Compare revisions offline with exact witnesses.

The parser may discover new relationships in retained markup without recrawl.
It cannot recover removed scripts, sensitive attributes, missing rendered
content or historical anchors not captured. Report `capture_insufficient` for
such cases; no hidden web fallback. Changing parser version is not permission
to re-fetch a source or expose a previously denied field.

For Markdown/TXT use retained approved bytes and line/UTF-8 spans. PDF/DOCX use
approved format-specific inert replay artifacts and page/item/relationship
provenance; preservation of visual/layout fidelity requires separate adapter
validation. Do not claim arbitrary sanitization preserves native binary
fidelity. Unsafe or unsupported native replay is refused, not silently rendered.

## 15. Source-storage scenarios — assumptions

**Hypothetical planning ranges, not measurements. Historical raw HTML is
unavailable.** Per page: raw transfer/decompressed-source planning proxy
100–1,000 KiB; compressed retained artifact 20–300 KiB; normalized sidecar
15–150 KiB; anchor/link registry 2–30 KiB; JSON-LD assertions 0–20 KiB.
These are illustrative independent ranges, not a measured compression ratio.
The selected design stores the admitted artifact, not both unrestricted raw and
compressed copies. Registry/assertion columns are separate incremental payloads
in this estimate, not duplicates inside the sidecar count.

Single-version retained payload = compressed artifact + sidecar + registry +
assertions = **37–500 KiB/page**. Tables in section 29 scale this transparently.
Transport bytes, logical knowledge-resource quota and physical storage are three
different quantities; no billing/quota implementation changes are proposed here.

## 16. Structural graph responsibilities

The graph is the source-provenance layer: document, section, heading, paragraph,
list/item, table/cell, FAQ, review, commercial block, directions, timeline,
warning, qualification, links and typed relationships where supported by the
parser. Unknown structures remain ordinary source blocks, not guessed ontology.

Retain nodes/edges even if they have no vector. Graph identity and provenance
are immutable; malformed edges and cross-version references fail validation.
Graph parenthood is not resource identity, semantic compatibility or permission.
Store exact content once where practical, with indexed scoped adjacency rather
than copying whole ancestors into every record.

## 17. Retrieval-entry responsibilities

A dense entry is a bounded **search representation**, not a merged fact. It
has full scope/revision/policy/profile identity, source-ordered child IDs,
exact child-to-entry UTF-8 intervals, heading provenance, typed boundary markers,
continuation/bundle references, token accounting and coverage status.

Several adjacent compatible evidence children may share it without changing
their text, attributes, provenance or evidence identities. No generated summary
or invented identity text. Synthetic separators/type labels are explicitly
non-evidence; original source text has exact mappings. Entry IDs incorporate
scope and policy, never just content hash.

Changing entry policy does not rewrite the graph or v1/H/I/J outputs. Every
eligible atom must be searchable through FTS even if it lacks a dense entry;
dense omissions/standalone decisions have auditable reasons. A dense hit routes
to mapped children, not directly into an answer citation.

## 18. Atomic evidence responsibilities

Atoms retain exact facts, local qualifications, typed attributes, group/bundle
identity, source order and complete/partial status. They support reranking,
requested-field coverage and citations. They are not every empty container,
inline link or graph node. Oversized logical units may need mapped slices, but
the original unit and mandatory companions remain identifiable.

The v1 specs used below are an available **proxy for an atomic-vector strategy**,
not a final atom-schema decision: they include heading units, continuations and
some grouped evidence. Do not mistake 13,213 graph nodes for required vectors.
Final packs must resolve entry text back to exact atoms and required companions;
a fragment cannot be labeled a complete table, review or timeline by itself.

## 19. Dense retrieval design

Future vectors attach to admitted contextual entries with the unchanged planned
profile: Gemini / `gemini-embedding-001` / version 1 / 768 dimensions. No vectors
or embedding calls in K. Profile changes are outside this design.

Query only the authorized active representation. Use bounded per-channel
candidates; validate manifest and scoped entry/atom mappings on materialization.
Dense similarity is relevance, never identity proof or negative evidence.
Missing/incompatible vectors are an explicit availability state governed by
the existing degradation contract, not a reason to claim a fact is absent.

An entry can route a conceptual question to several children. It cannot justify
using all children in the answer, joining neighboring entities or asserting
catalog exhaustiveness. Phase 6 ranking must measure dilution and resource
diversity, not assume fewer vectors improve quality.

## 20. Atomic PostgreSQL FTS design

Index searchable atomic content with the exact scoped source/revision identity,
not only coarse dense text. Preserve canonical text and provenance independently
of lexemes. Parameterized PostgreSQL FTS ranks before LIMIT and applies the same
authorization/lifecycle predicates as dense search.

An FTS hit resolves directly to the atom and its mapped entry/structural parent,
source version and scope. A heading-only/orphan atom without a dense entry still
has a legal lexical route. Missing entry maps do not erase a valid child hit.
Use a scoped inverted membership lookup, not a corpus scan.

Atomic indexing preserves the *opportunity* to find child-only terms. Current
English stemming/tokenization is not guaranteed to preserve arbitrary SKU,
punctuation-rich error codes, languages or monetary notation exactly. Test
those witnesses before rollout; a later exact-token field/config would need its
own authorization. K neither changes FTS configuration nor promises universal
exact-string recall from stemming alone.

## 21. Future RRF design

Target flow: authorized dense entries + authorized atomic FTS -> rank-only
weighted RRF -> normalized structural seeds -> reranking -> bounded expansion
-> exact atoms -> coverage -> final pack. Current Phase 2 formula stays:
`score = dense_weight/(k + dense_rank) + fts_weight/(k + fts_rank)`;
one-based ranks, absent channel contributes zero, deterministic ties.

The channels have different units, so **do not fuse an entry ID and an atom ID
as if they were the same object**. Proposed typed adapter before fusion:

1. Use canonical scoped entry routing keys. Dense supplies ranked entries.
2. FTS hits map to their primary entry routing key while retaining every exact
   hit atom. An atom without an entry uses a distinct atomic-only routing key.
   A continuation has an explicit mapping policy, not arbitrary parent choice.
3. Order unique lexical routing keys by their best original atom rank, then
   stable scoped key; assign one-based channel ranks. Record original atom
   ranks/scores separately. Multiple matching children must not sum into an
   unbounded parent boost; multiple dense entries must not multiply one atom's
   support. Never compare cosine and FTS scores directly.
4. RRF ranks routing keys. Normalize selected keys into scoped structural seeds
   carrying exact lexical hits and bounded dense membership. Reserve exact
   lexical witnesses within their channel/coverage budget before expansion;
   broad parents cannot erase them merely by having many children.

This preserves rank-only fusion while making the changed unit explicit. It
requires future offline adapter tests and trace/version/cache identity; it is
not claimed equivalent to today's chunk-level ranking. Deduplicate atoms after
normalization; routing scores are not evidence confidence. Channel failures
remain explicit dense-only/FTS-only/technical-failure states, with no hidden
legacy lexical fallback.

## 22. Future structural expansion design

Batch-fetch authorized exact seed atoms and bounded entry memberships. Expand
only allowed parent/child, same-section neighbor and validated semantic edges.
Require current source/revision for every hop; a link alone cannot trigger a
fetch, grant access or walk a whole website. Keep visited scoped IDs and depth,
atom, token, mapping and DB-roundtrip budgets; no per-child N+1 queries.

Initial design envelope for later review: up to the existing 48 seed contract,
one local structural hop, two ordered neighbors each side, at most 32 mapped
evidence-unit references per entry and an independent final token budget.
Mandatory qualifier/header/bundle completion uses explicit bounded references,
not unlimited ancestor recursion. If required evidence cannot fit, mark partial
coverage rather than silently sever its qualification.

Reranking is on exact atoms/typed bundles with bounded context. Final pack cites
only exact authorized content; source links come from that evidence. No parent
substitution threshold, auto-merging retriever or query-specific expansion rule.
Phase 7 must retain the seed/witness and trace why each extra atom was admitted.

## 23. Generic entry-sizing policy

Proposed starting envelope: **target 500 total local tokens; soft 250–700; hard
800; inherited context at most 80; at most 32 evidence-unit references and 256
mapping intervals per entry**. All markup/separators/context count. These are
offline review candidates, not enabled settings or a provider billing estimate.

General source-order procedure, to implement only after K approval:

1. Traverse one immutable source/section at a time. Select searchable children
   without mutating evidence; retain all graph and lexical identities.
2. Inherit bounded exact heading ancestry; do not synthesize resource names or
   remove evidence qualifiers to make room. Record context omissions precisely.
3. Accumulate adjacent eligible children, preserving explicit per-child text,
   boundaries and byte mappings. Stop at section exit, proven resource change,
   navigation/quality transition, unresolved typed ownership boundary, or any
   token/fanout/mapping budget. Equal unknown resource IDs never prove identity.
4. Close near target at a valid child boundary. A short compatible tail may fit
   up to the soft ceiling; a whole unit may use the hard ceiling. Do not cross
   a protected boundary merely to meet the soft minimum.
5. For an oversized child, produce source-mapped continuation slices with its
   immutable logical-unit ID and required companions. Mark partial states;
   never truncate silently or delete the original evidence unit.
6. Permit peers to share a *routing entry* only under this policy. This does not
   call or relax H's evidence packer or assert semantic equivalence between peers.

No corpus-global clustering, all-pairs identity comparison or minimum vector
count. Per-source streaming plus bounded ancestry/mapping tables gives linear
construction in source tokens, nodes and mappings. A very short section remains
short. Cross-section packing and learned/query-dependent summaries are excluded
from the initial slice. Any over-budget source fails visibly, not partially READY.
The policy tokenizer/version must be fingerprinted. Local cl100k counts are not
Gemini's billing tokenizer; the later embedding boundary must separately verify
provider input limits without silently truncating or changing the fixed profile.

## 24. Heading policy

Default: preserve heading nodes in the graph, inherit eligible exact headings
as contextual metadata, and keep lexical access. A vector is not automatic.
Standalone dense headings are allowed for no-useful-descendant/orphan cases,
independently informative headings or another reviewed general rule with a
discoverability witness. A question, warning, number or fact in a heading cannot
be discarded solely because it resembles a section label.

An independently useful heading can be represented in mapped descendant search
context only if coverage is proven; otherwise it remains standalone. Unknown
cases stay searchable. K neither expands I's reviewed taxonomy nor reclassifies
the 754 v1 heading units. The arithmetic estimate below deliberately models
ideal contextual handling and is **not** proof that all headings can lose vectors.

## 25. Typed-evidence policy

Lists, tables, reviews, FAQ, timeline stages, commercial roles, directions,
warnings and qualifications remain separate logical evidence units. Sharing a
search entry never makes a price into a guarantee, a review into product fact,
a later timeline stage into an earlier one, or one entity's directions into
another's. The same applies to clauses, rooms, service limits and prerequisites.

Mandatory companions and completeness flags survive slicing. Table headers
and cell coordinates, list item ordinals, question/answer ownership, timeline
stage/qualification and source roles remain in the graph/atom contract. Typed
ownership uncertainty is a boundary, not permission to infer a common subject.
No medicine/product-specific branch and no change to existing typed safety gates.

## 26. Normalized scale metrics and offline method

Denominator: **201,377 local cl100k source tokens** in 763,997 UTF-8 bytes from
the 23 saved raw-text fields; not legacy chunk tokens, raw HTML, billing tokens
or live data. Reconstructed native graphs preserve actual source versions and
contain **13,213 nodes, 6,700 edges**. Existing v1 serialization yields **3,242
specs, 278,491 tokens, 18,137 mapping rows**. No corpus mutation occurred.

Required metrics for later implementation: entries and vectors/1,000 source
tokens; entry/source token multiplier; evidence units/entry; heading-only %;
small-entry % (<250); min/p50/p95/max total tokens; max child/mapping fanout;
exact primary/inherited/overlap mapping coverage; byte/token index growth;
processing time and peak memory per source. Count deliberately lexical-only
atoms separately; do not call them lost evidence or hide them from coverage.

Measured v1 proxy A: 16.099157301975897 vectors/1,000 source tokens;
1.3829335028329948 token multiplier; min/p50/p95/max **3/55/264/656**;
754 heading units (**23.257248612%**); 3,058 small units (**94.324491055%**).
Graph-member fanout per spec: min/p50/p95/max **1/2/13/42**, total 12,106 member
references. Graph members are not the same as future logical evidence units.

**Arithmetic estimate B, not a retrieval-entry implementation:** group nonheading
v1 proxy units by document and exact heading path (740 groups). Sum their
`token_count - prefix_tokens`: 190,363 proxy body tokens. For target `t`, reserve
80 context tokens per modeled entry and calculate per group
`n = max(1, ceil(body/(t-80)), ceil(children/32))`. Divide the group's token total
evenly into n arithmetic slots to show a size distribution. No text is packed,
no entry IDs/mappings are produced and no boundary rule is weakened.

| Modeled total target | Entries | Tokens | Entries/1,000 source tokens | Token multiplier | min/p50/p95/max | Small slots |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| 400 | 1,091 | 277,643 | 5.417699141411383 | 1.3787224956176722 | 82/265/395/400 | 515 |
| 500 | 974 | 268,283 | 4.836699325146367 | 1.332242510316471 | 82/242/482/500 | 497 |
| 600 | 906 | 262,843 | 4.499024218257299 | 1.3052285017653456 | 82/226/579/598 | 497 |

These are **optimistic token-envelope scenarios**, not realizable counts or
strict mathematical lower bounds for the final policy. They ignore actual
qualification/resource/typed cut positions, exact separator tokenization and
standalone heading exceptions; even subdivision can split logical units. Actual
entries/mappings may be substantially higher. At target 500, arithmetic average
is 2.5544147843942504 nonheading proxy units/entry; 51.026694045% slots remain
small. The mean/ceiling does not prove actual fanout compliance. Full mapped
coverage for B is **not yet measured**; required future gate is 100% of admitted
searchable evidence, with every omission explicit.
The envelope assumes zero standalone heading entries; actual heading-only
percentage and maximum child/mapping fanout remain unmeasured, not zero.

The 600 envelope lowers count partly by enlarging routing context and does not
solve section fragmentation. Choose 500 provisionally to balance dilution and
mapping cost, not to hit an absolute corpus count. Token cost changes much less
than vector count; no claim of proportional embedding-token savings.

## 27. 1x/10x/100x analysis

Analytical repetition, not repeated customer ingestion. For each copy, generate
a deterministic hash of replica/org/bot/document/version identity; checked
**23/230/2,300 distinct scoped source identities**. Content is intentionally
identical but not deduplicated across tenants. Only identity sets and arithmetic
totals are materialized, not a 100x corpus or embeddings.

| Scale | Sources | Source tokens | Graph nodes | A vector proxy | B500 vector envelope | B500 entry tokens | Existing evidence maps | Minimum B body-unit memberships |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1x | 23 | 201,377 | 13,213 | 3,242 | 974 | 268,283 | 18,137 | 2,488 |
| 10x | 230 | 2,013,770 | 132,130 | 32,420 | 9,740 | 2,682,830 | 181,370 | 24,880 |
| 100x | 2,300 | 20,137,700 | 1,321,300 | 324,200 | 97,400 | 26,828,300 | 1,813,700 | 248,800 |

Densities remain 16.099157301975897 (A) and 4.836699325146367 (B500 envelope).
Graph edges scale 6,700/67,000/670,000. A entry tokens scale
278,491/2,784,910/27,849,100. The minimum B membership row counts exclude
continuation splits, inherited headings and per-span entry maps; they are not
a storage forecast or an exact preservation proof. Existing evidence maps remain
separate and must not be replaced by fewer coarse memberships.

Construction target: O(T+N+E+M) per corpus with bounded depth/fanout; streaming
memory O(largest admitted source plus current entry/mappings), not O(all tenants).
Version updates rebuild only changed sources and their scoped derived indexes.
Retrieval uses indexes and bounded candidate/expansion budgets, not all corpus
nodes. DB index build/query complexity and physical memory/latency were **not
benchmarked** here. Corpus-wide all-pairs/clustering and customer-specific
thresholds are rejected.

## 28. Domain and format generalization

| Domain/format | Same-policy application | Boundary/coverage witness |
| --- | --- | --- |
| Commerce | Source-ordered blocks within section/resource | Price role, review ownership, ingredients and qualifications stay separate. |
| Hotel | Room/service/terms sections | Breakfast, check-in and cancellation remain attached to the correct room/rate. |
| Software | Plan/feature/terms sections | Storage units, limits and renewal qualifiers do not move between plans. |
| Course | Module/requirements sections | Prerequisites, duration and certificate statements remain exact. |
| Legal | Clause/subclause structure | Numbered clause, exceptions and cross-references preserve scope. |
| Technical documentation | Heading/code/paragraph structures | Punctuation-rich error code and warning have lexical/evidence witnesses. |
| General article | Ordinary sections and paragraphs | A quoted speaker is not the document author; nearby navigation is not evidence. |
| Markdown | Native headings/lists/links and byte spans | Literal links retained, missing HTML anchors not invented. |
| TXT | Document/paragraph/line structure | No guessed heading/resource hierarchy required to make bounded entries. |
| PDF | Approved page/item/bbox plus reading order | Table/caption/footnote links need adapter provenance; no fake HTML fragments. |
| DOCX | Paragraph/list/table/relationship identities | External links stay inert; archive/macro safeguards precede parsing. |

This is a contract-level generalization review, **not measured retrieval quality
on seven industry datasets or a new PDF/DOCX parsing run**. The next slice needs
domain-neutral GOLD fixtures and unchanged existing format regressions. No
business category selects different runtime packing limits.

## 29. Source-storage scenarios — scaled payload

GiB = 2^30 bytes. Single retained version, no replicas or DB overhead. Inputs are
section 15's assumptions; none is measured raw HTML from the saved corpus.

| Pages | Raw source proxy (not additionally retained) | Compressed admitted artifact | Structural sidecar | Anchors/links | Structured assertions | Retained total |
| --- | --- | --- | --- | --- | --- | --- |
| 100 | 0.009537–0.095367 | 0.001907–0.028610 | 0.001431–0.014305 | 0.000191–0.002861 | 0–0.001907 | 0.003529–0.047684 |
| 1,000 | 0.095367–0.953674 | 0.019073–0.286102 | 0.014305–0.143051 | 0.001907–0.028610 | 0–0.019073 | 0.035286–0.476837 |
| 10,000 | 0.953674–9.536743 | 0.190735–2.861023 | 0.143051–1.430511 | 0.019073–0.286102 | 0–0.190735 | 0.352859–4.768372 |
| 100,000 | 9.536743–95.367432 | 1.907349–28.610229 | 1.430511–14.305115 | 0.190735–2.861023 | 0–1.907349 | 3.528595–47.683716 |

Formula: pages × KiB/page ÷ 1,048,576. Multiply by retained versions and physical
replicas only as separately stated scenarios; dedup/compression cannot be assumed
to save cross-tenant storage. Inert minimization may change compression and page
size substantially. Large PDF/image-heavy sources need separate measurements.

Retention must eventually remove tenant-scoped artifact, sidecars, graph,
entries, vectors, FTS rows, mappings and caches through an auditable deletion
lifecycle, including backup-expiry obligations. Immutable means not overwritten,
not exempt from deletion. Sharing a physical object must never make another
tenant's ownership or existence observable; initial design avoids cross-tenant
dedup entirely. No retention setting or cleanup code changes in K.

## 30. Vector and total storage scenarios

Fixed future profile: **Gemini / gemini-embedding-001 / v1 / 768 dimensions**.
Float32 payload lower bound: **768 × 4 = 3,072 bytes/vector**. This excludes
pgvector value/tuple/page overhead, ANN indexes, WAL, dead tuples, FTS indexes,
entry text, mappings, graph, source artifacts, backups and replication.

Hypothetical densities (not production recommendations), raw vector **MiB**:

| Source tokens | 2 vectors/1k | 5 vectors/1k | 10 vectors/1k | 16 vectors/1k |
| --- | ---: | ---: | ---: | ---: |
| 100,000 | 0.585938 | 1.464844 | 2.929688 | 4.687500 |
| 1,000,000 | 5.859375 | 14.648438 | 29.296875 | 46.875000 |
| 10,000,000 | 58.593750 | 146.484375 | 292.968750 | 468.750000 |
| 100,000,000 | 585.937500 | 1,464.843750 | 2,929.687500 | 4,687.500000 |

On the current arithmetic dataset only: A lower bound 9.498046875 MiB;
B500 envelope 2.853515625 MiB; document-parent C 0.0673828125 MiB. Corresponding
A/B500 vector bytes per saved source byte: 13.035946476229618 /
3.9164132843453574. Tiny C storage does not make its retrieval acceptable.

Physical planning must separately measure:
`vector payload + vector tuples + ANN + FTS/text + entry-to-atom/span maps +
graph/edges + artifacts/sidecars + WAL/vacuum headroom + backups/replicas`.
No single multiplier is asserted for those components. For illustration only,
100 bytes per mapping row would make 18,137 existing evidence maps 1,813,700
bytes before indexes; actual row encoding/index cost is unmeasured. Lower vector
count does not remove atomic FTS or source-graph cost.

## 31. Future retrieval witnesses

These are a proposed evaluation set, **not new user queries or executed tests**.
Use synthetic held-out values, two tenants with identical text, stale versions,
and an unauthorized stronger match for every class. No query-specific runtime rule.

| Witness | Dense routing expectation | Atomic lexical expectation | Expansion/evidence expectation |
| --- | --- | --- | --- |
| Ingredient/list-only exact term | Relevant list/section entry can route concept query | Exact child term recoverable even if dense misses | Correct list item, header and qualifying context, not another resource. |
| Review phrase | Review block route, not product fact | Phrase survives in exact review atom | Reviewer/owner provenance; no neighboring-card attribution. |
| FAQ answer | Question+answer relation routes | Answer-only term still reachable | Paired question, answer, qualifiers. |
| Exact price | Commercial block routes | Number/currency lexical witness tested explicitly | Correct role/unit/entity and qualifiers, not all monetary amounts. |
| Dosage | Instructions route | Exact quantity/unit hit | Complete instruction and warning companions. |
| Timeline range | Stage-containing entry routes | Range/stage term in atom | Correct stage and qualified claim; no guaranteed results. |
| Warning | Warning or parent section route | Exact warning wording reachable | Negation/exceptions retained, not averaged away. |
| Ordinary prose | Conceptual paragraph route | Rare proper noun remains searchable | Local paragraph and necessary antecedent. |
| Hotel cancellation | Terms section routes | Deadline/fee term hit | Rate/room scope and exceptions retained. |
| Software storage limit | Plan section routes | Quantity/unit/plan identifier hit | Limit plus renewal/account qualifiers, no cross-plan blend. |
| Course module | Course/module entry routes | Module code/title hit | Correct parent course and prerequisite links. |
| Legal clause | Relevant clause routes | Clause identifier/phrase hit | Scoped exceptions and permitted references, bounded hops. |
| Technical error code | Troubleshooting context routes | Literal code behavior tested against FTS tokenizer | Exact code, procedure and safety warning. |

Score channel recall separately, witness survival after RRF/rerank, exact mapping
coverage, final evidence completeness, tenant/version leaks, fanout and latency.
An inaccessible/missing witness must remain missing/technical/partial, never a
fabricated answer or unsupported absence claim. Do not use final prose quality
as a substitute for evidence-path measurements.

## 32. Strategy comparison

| Dimension | A: one vector per evidence proxy | B: contextual dense + atomic FTS | C: very coarse section/document parents |
| --- | --- | --- | --- |
| Count on available data | 3,242 v1 units, measured | 974 at target-500 arithmetic envelope; actual policy unimplemented | 23 whole-document parents; 740 nonheading section groups before any cap |
| Size | p50 55, p95 264 local tokens | Modeled p50 242, p95 482; boundary-sensitive | Whole-document p50 9,370, max 15,787; all 23 exceed proposed hard 800 |
| Mapping fanout | Often one logical unit, up to 42 graph members | Several units; proposed 32 unit/256 interval caps; actual unmeasured | Potentially entire section/document; not bounded by evidence suitability |
| Direct semantic discovery | Child has its own vector; very short text may lack context | Better contextual routing is plausible, not proven; child detail may dilute | Fine facts easily dilute; no exact child guarantee |
| Lexical child access | Available if atomic FTS retained | Required independent atomic FTS route | Poor if parent-only lexical; adding atomic FTS still needs exact mapping |
| False-absence risk | Top-K saturation/fragmentation | Bounded routing may miss a child; lexical reservation/coverage needed | High if parent hit/miss is mistaken for complete evidence |
| Storage | Many vectors and repeated prefixes | Fewer possible vectors, unchanged atoms/graph plus entry maps | Few vectors but large text/expansion; cheap vectors alone misleading |
| Retrieval complexity | More candidates, simpler vector-to-unit map | Typed routing adapter and bounded scoped expansion required | Broad reranking/expansion unless separately capped |
| Phase 6/7 compatibility | Useful baseline, retains exact evidence | Explicit Phase 6 rank units and Phase 7 exact-child expansion | Parent substitution obscures coverage unless redesigned |

Whole-document C is not valid under the proposed token policy. Truncating or
summarizing it would create another unmeasured strategy; splitting it eventually
approaches B. Small sections also occur in C, so coarse grouping does not
guarantee good utilization. A remains a required comparison baseline/fallback
for offline quality evaluation. B is chosen for architecture, not a claimed
measured recall win or guaranteed count reduction.

Section-parent C arithmetic: 740 groups, 249,563 tokens including the assumed
80-token prefix; min/p50/p95/max **82/177/1,027/8,266**. **68 groups exceed 800**.
Nonheading proxy child fanout min/p50/p95/max **1/2/10/84**. Thus section parents
also need splitting/bounded membership; replacing every section with one vector
is not an adequate generic policy. As with B, this is an arithmetic view of
existing heading groups, not newly constructed search entries.

## 33. Source-capture decision

**C — ANOTHER DESIGN: immutable privacy-minimized inert replay artifact +
bounded normalized sidecar.** It combines replayable retained structure with
explicit safe provenance while refusing unrestricted raw retention. Record
original and retained hashes, minimization/fidelity manifest and independent
parser revisions. No secret/header/session/form/browser-state capture.

Compared with sidecar-only storage it preserves more future parser options;
compared with raw+sidecar it trades deliberate fidelity losses for defensible
privacy boundaries. Missing data remains missing and may require a separately
authorized fresh capture. Capture security/fidelity acceptance is a prerequisite
to rollout, not solved merely by adopting an OSS HTML backend.

## 34. Retrieval-representation decision

**B — CONTEXTUAL DENSE RETRIEVAL ENTRIES + ATOMIC POSTGRESQL FTS + BOUNDED
STRUCTURAL EXPANSION.** Preserve structural and typed evidence exactly while
decoupling vector allocation from atom count. Retain lexical access to narrow
facts and make dense/lexical rank-unit conversion explicit and traceable.

No weakening of subject, qualification, resource or source-version boundaries.
The additional membership/ranking complexity is justified only if later offline
witness tests show no material recall/completeness regressions. No activation
permission follows from this design decision.

## 35. Implementation-order decision

**1 — general retrieval-entry implementation first, offline only.** Frozen
sources already support testing token accounting, scoped identity, headings,
typed boundaries, mappings, linear construction and the count-vs-coverage
tradeoff. This resolves the representation uncertainty blocking Phase 4
evaluation without provider calls, source acquisition or schema changes.

Capture enrichment cannot repair historical source omissions and requires new
authorized fetches plus security/retention decisions. It should follow as a
separately reviewed admission/sidecar slice. Its absence must remain explicit
in offline evaluation; do not infer cards, anchors or reviews to make B pass.
Dense/FTS serving, ranking and expansion implementation belongs to later
authorized integration work, not the next serializer slice.

## 36. Risks, limitations and K validation

Concrete remaining risks:

- Arithmetic envelopes do not prove safe packing, heading discoverability,
  child fanout, exact mapping coverage or retrieval quality. Protected boundaries
  may keep vector count high; the next evaluator must report that honestly.
- Dense aggregation can dilute exact terms; current English FTS can lose
  punctuation/language distinctions. Witnesses must validate both channels.
- Parent/child rank projection can crowd out resources or overcount support.
  Canonical routing keys, reserved lexical witnesses and trace tests are required.
- Untrusted source assertions can misattribute entities or inject instructions;
  scope, exact provenance and non-executable processing remain mandatory.
- Inert minimization loses some future replay fidelity; public body text can
  contain unexpected private data. A generic secret scanner is not a guarantee.
- Immutable version retention, atomic publication, cache invalidation and deletion
  are prerequisites not implemented by this phase. Never publish a second READY
  representation through today's selectors.
- Historical Markdown cannot validate HTML capture/anchor completeness, native
  file replay fidelity or production memory/latency. Fresh authorized fixtures
  and later integration acceptance remain necessary.

K validation: offline arithmetic executed with socket connection/DNS entry
points denied; local cached tokenizer only; no DB/provider/embedding calls or
external fetch in the helper. Research network was restricted to official OSS
source; no evaluation-site access. Reconstructed existing source-native graphs
and v1 specs using unchanged pure functions. No retrieval-entry builder or
source-capture code implemented. No tracked Python file added, so canonical
suite rerun was optional and not performed.

Preservation inventory extends J's 684 hashes to **702 protected files**,
including J/H/I/v1 frozen outputs and committed code (ledger excluded as the
authorized documentation edit). **Final verification: 702/702 hashes PASS**;
secret scan and `git diff --check` PASS. Only this Markdown and the ledger
appear in final git status. Ignored calculation/results are not staged.

Ignored audit artifact SHA-256 pins:

| Artifact | SHA-256 |
| --- | --- |
| `measurements.json` | `782617ddc090089f74b7116254caa9c40d45c7daac4689a2c04bf22a68bfcd94` |
| `calculate.py` | `c0b19f700970deba0a2ea2003a2f86a75c73a4eff32f29ada14a21d20f8a02e2` |
| `research_hashes.json` | `d828d18f2e9b9625911a32cc52b4432bc2c406db0bd12a42b42d08a2449369d1` |

Reproduction: from repository root, run the existing backend venv with `-B`
against `.codex_structural_4_1k/calculate.py measure`; it performs no network/DB
operations and writes ignored arithmetic outputs only. Method and all material
formulas/results are recorded above for review without the ignored helper.
Percentiles use nearest-rank. No broad tests, live queries, DB access, corpus
mutation, provider calls, recrawl, embeddings, activation, push or deployment.

## 37. Exact next phase

**Proposed Phase 4.1L — offline contextual retrieval-entry contract, serializer
and mapping/coverage evaluator. Requires separate approval.**

Scope: immutable entry/membership/span DTOs with full trusted identity and
policy fingerprint; deterministic bounded section-local construction over the
existing frozen graph/atomic evidence; exact byte mappings; explicit heading,
typed-unit/qualification/continuation treatment; token/fanout/coverage ledger;
domain-neutral GOLD plus existing corpus evaluation at 1x/10x/100x.

Acceptance: no graph/v1/H/I/J mutation; same text in different tenants gets
different identities; stale/cross-scope maps fail closed; 100% admitted evidence
has exact atomic/lexical coverage with explicit dense disposition; hard budgets
hold including prefixes; unsupported ownership remains unknown; deterministic
linear construction; representative witness routing/mappings preserved; focused
structural/canonical tests, preservation, secret scan and whitespace checks pass.
Report actual counts/distributions without an absolute count target.

Explicit exclusions: no Firecrawl/crawler/source-capture implementation, schema
or storage changes, database writes, embeddings, vector/FTS/RRF serving change,
planner/reviewer/generation change, activation, recrawl or production action.
Do not begin this slice as part of K. **K remains uncommitted for review.**
