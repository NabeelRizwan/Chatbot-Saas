# Phase 4.1D — isolated offline Docling PDF/DOCX adapter

Date: 2026-09-16. Branch: `main`. This is an offline implementation and synthetic
extraction evaluation, not production ingestion acceptance.

## 1. Phase 4.1C checkpoint

Audited the eight expected Phase 4.1C paths, including the sole application
dependency change `markdown-it-py==4.2.0`, runner registration and research ledger.
Fresh structural tests: **296/296 PASS, 0.538 s**. Secret-pattern and staged
whitespace checks passed. No corpus, provider, DB or retrieval change was found.

Committed **only Phase 4.1C** locally:

`6017dcdc1b87c0023c240c7f253f0a4e69a6e2a3`

`Phase 4.1C: add deterministic Markdown and text structural adapter`

The tree was clean immediately afterward. Phase 4.1D remains uncommitted. Nothing
was pushed. Prior Phase 4.1B checkpoint `f0835c16f0b38ea2230e2470f4667b41256914c6`
is preserved in its ancestry.

## 2–4. Selected release, actual source and dependencies

Inspected official source **before implementation/install**, not merely API
documentation. Selected [Docling v2.127.0](https://github.com/docling-project/docling/releases/tag/v2.127.0),
commit `014e8e357b24aa9d5113317fa454df8a70de9aeb`, released 2026-09-14, MIT,
Python >=3.10,<4. The local interpreter is Python 3.12.14 on Windows, CPU only.
Core is 2.96.1, commit `a7ba70940ef39c64339c938b75791536c691958f`, MIT.

Use the current modular `docling-slim` distribution, not the all-formats/standard
bundle. `requirements-structural-docling.txt` is **optional and not included by
application requirements**. Selected extras: convert-core, format-docx,
format-pdf, models-local. Explicit pins:

| Package | Version | License review |
| --- | --- | --- |
| docling-slim | 2.127.0 | MIT |
| docling-core | 2.96.1 | MIT |
| docling-parse | 7.20.0 | MIT; native bundled dependency notices remain applicable |
| docling-ibm-models | 4.0.2 | MIT |
| torch | 2.14.0 | Apache/BSD/MIT/BSL and LLVM exception; distribution notices retained |
| torchvision | 0.29.0 | BSD |
| transformers | 5.17.0 | Apache-2.0 |
| opencv-python-headless | 4.13.0.92 | Apache-2.0 and bundled notices |
| pypdfium2 | 5.13.0 | BSD-3-Clause/Apache-2.0 and PDFium dependency notices |
| pypdf | 6.16.2 | BSD-3-Clause |
| python-docx | 1.2.0 | MIT |
| Pillow | 12.3.0 | MIT-CMU |

Reviewed the resolver dry-run, Windows wheels, dependency metadata, Python
constraints and package sizes first. The initial plan added 26 packages, roughly
180 MB of wheel downloads. TableFormer then exposed its required optional `cv2`
extra: reviewed and pinned IBM-models' supported OpenCV 4 headless extra (roughly
40 MB), not OpenCV 5. No alternative parser framework was installed; no existing
application package upgrade/uninstall was needed. `pip check`: **PASS**, no broken
requirements. This is a tested local optional environment, not a universal
cross-platform lock or a vulnerability/security certification of upstream code.

## 5. Local model policy

Default Docling model acquisition can download on first use; setting
`enable_remote_services=False` alone is insufficient. The adapter instead
requires an explicit, pre-provisioned cache and verifies five SHA-256 hashes
before PDF conversion. No normal parse path contains a downloader.

| Artifact | Immutable revision | License | Files |
| --- | --- | --- | --- |
| Heron layout | `docling-project/docling-layout-heron@8f39ad3c0b4c58e9c2d2c84a38465abf757272d8` | Apache-2.0 | safetensors, config, preprocessor config |
| TableFormer accurate | `docling-project/docling-models@fc0f2d45e2218ea24bce5045f58a389aed16dc23` (v2.3.0) | CDLA-Permissive-2.0 | safetensors, model config |

Deliberately provisioned those five files only, in ignored
`.codex_structural_4_1d/models`. Total **384,428,156 bytes (366.62 MiB)**; weights
alone are 171,658,996 + 212,758,388 bytes. Exact file hashes are in the adapter's
`MODEL_FILES` allowlist. Missing, corrupt, symlinked/escaping or extra unreviewed
files in either model repository subtree fail visibly. No model cache enters Git.
No OCR/VLM/caption model or provider credential is provisioned by this slice.

## 6. OSS implementation ledger

Extended `PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md` with pinned source files,
classes/functions, licenses, adapted patterns and rejected assumptions for:

- Docling converter, PDF/Simple pipelines, DOCX backend, layout and table stages.
- Docling Core document/text/header/list/table/picture/provenance/coordinate types.
- RAGFlow/DeepDoc PDF positions and table/DOCX boundaries.
- LlamaIndex page metadata and the limitations of flattened DOCX text.
- Haystack link-as-data handling and page references.
- Onyx native parser resource ownership and explicit error handling.

**No literal source blocks copied.** Public pinned Docling/Core interfaces are
used directly. Other systems supply design patterns only. Their datastores,
permissions, indexing, enrichment and orchestration were not adopted.

## 7. Phase 4.1D files

Modified:

- `backend/scripts/test_scoped_rag_regressions.py` — register the new suite only.
- `docs/PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md` — source study/policy addendum.

New:

- `backend/requirements-structural-docling.txt`
- `backend/services/structural_docling_adapter.py`
- `backend/scripts/structural_docling_worker.py`
- `backend/scripts/build_structural_docling_fixtures.py`
- `backend/scripts/evaluate_structural_docling_adapter.py`
- `backend/test_structural_docling_adapter.py`
- `backend/tests/fixtures/structural_gold_docling_v1/{workshop.pdf,merged.pdf,image_only.pdf,empty.pdf,rotated.pdf,encrypted.pdf,workshop.docx,manifest.json,expected.json}`
- `backend/tests/fixtures/structural_gold_docling_v1/.gitattributes` — fixture-local binary declarations added during the checkpoint audit; preserve PDF/DOCX bytes under Windows Git line-ending settings.
- `docs/PHASE_4_1D_DOCLING_ADAPTER_REPORT.md`

No application ingestion, schema, repository, requirements, frontend, retrieval,
model/provider selection or frozen Phase 4.1A contract file changed in 4.1D.

## 8. Boundary and caller ownership

`owned immutable bytes + RevisionIdentity + explicit format/fidelity`
→ isolated private child converter → serialized Core extraction record
→ validated, provider-neutral `StructuralDocument`.

The parent module imports neither Docling nor the ORM. Docling classes never
escape into repository/schema/retrieval APIs. Input must be immutable bytes, not
a URL or a path extracted from document metadata. Caller-supplied organization,
bot, document, source version/hash and structure revision are validated; bytes
must match the supplied SHA-256. Parser metadata cannot override ownership.

Output stays in memory/ignored evaluation artifacts. State is STAGING, source
quality UNKNOWN/manual_review, no chunk mappings. This boundary validates
identity consistency; it is **not** a substitute for the trusted caller's future
authorization check.

## 9. Explicit Docling → DTO mapping

| Docling representation | Our frozen DTO | Preservation policy |
| --- | --- | --- |
| document/body/furniture | DOCUMENT + GROUP | Stable item paths, original tree order |
| title/section header | SECTION + HEADING | Explicit children and HEADING_FOR; no inferred business role |
| TextItem | PARAGRAPH | `orig` preferred to normalized `text`; unknown text labels retained |
| ListGroup/ListItem | LIST/LIST_ITEM | Order, membership, nesting; mixed modes split into consecutive typed runs under original GROUP |
| TableItem/TableData | TABLE/TABLE_ROW/TABLE_CELL | Actual sparse cells, coordinates, spans and supported header refs; not padded computed grid |
| RichTableCell refs | cell plus referenced subtree | Preserve once; cycle/duplicate/missing/orphan refs fail |
| PictureItem/caption | MEDIA + caption text | Local structural reference and source-backed caption; no generated description |
| hyperlink | LINK child | Original target as inert data, existing safe-link rules, unresolved target |
| provenance | parser_item and genuine page_bbox | No invented byte offsets or DOCX pagination |
| unknown text/nontext label | PARAGRAPH/GROUP | Preserve declared children/text; invalid graph fails, no silent orphan dropping |

## 10–12. PDF, DOCX and OCR behavior

PDF uses StandardPdfPipeline, local CPU layout/TableFormer, text layer, heading
hierarchy enabled. All OCR, image descriptions/classification, chart/code/formula
enrichment, remote services and plugins are disabled. Core original text and tree
are mapped without a Markdown/prose intermediate.

DOCX uses the public WordFormatOption/SimplePipeline and MsWord backend; remote
and local external resource fetch and chart-image rendering are disabled.
Lists, nested lists, merged tables, text, hyperlinks and picture/caption items
are preserved. The backend's first-row-is-header default is **not accepted as
source evidence**: only explicit `w:tblHeader` rows survive. Table count, dimensions
and first-row source text must agree before associating those labels; flattened
1x1 layout tables cannot shift header flags. Mismatch raises
`DOCX_TABLE_ASSOCIATION` instead of guessing.

OCR is deliberately **not provisioned**: `ocr_used=false`, engine/confidence null,
pages empty. Requesting OCR fails `OCR_NOT_PROVISIONED`. Image-only/empty PDFs fail
`OCR_REQUIRED_OR_EMPTY_PDF`; mixed text/textless PDFs fail
`TEXTLESS_PAGE_UNSUPPORTED`, including a genuinely blank page. This conservative
restriction prevents falsely complete extraction while OCR is unavailable.

The rotated fixture exposed upstream reversed reading order; all nonzero PDF page
rotations now fail `ROTATED_PDF_UNSUPPORTED`. No automatic page rotation or OCR
repair was added. Native DOCX charts, external embedded resources and unsupported
vector/OLE/macro media are explicitly refused, not silently flattened or dropped.

## 13. Provenance and coordinates

Every node has a source-qualified `parser_item` span. Original item references
remain present even when wrapper SECTION/LIST/ROW nodes are added; generated paths
are structural derivations, not invented offsets into the PDF/DOCX bytes.

PDF provenance preserves actual one-based page numbers, original TOPLEFT or
BOTTOMLEFT origin, and 72-point units. The t/b endpoints become numeric y-min/max;
there is **no Y-axis flip, scaling or normalization**. Invalid/nonfinite/negative,
out-of-page or reversed coordinates fail. Cell bbox is used only when genuinely
provided and associated with one unambiguous table page; a table bbox is not
fabricated as the cell's bbox. DOCX never receives page/bbox or byte-offset claims.

## 14–17. Tables, lists, media and relationships

One DTO cell per actual backend cell, preserving row/column spans. Reject
overlaps, invalid offsets and oversized tables. Source-supported row/column
header relationships are retained; no units, prices or commercial roles inferred
from position. A merged cell spans columns without creating duplicate cell text.

List containers retain complete source block membership, order and nesting. A
mixed numbered/bullet Docling group is retained as GROUP with consecutive typed
LIST children; no list item becomes a disconnected paragraph. Number/bullet text
remains verbatim in the DTO. Only the evaluator removes an exact upstream-declared
marker to compare label-only GOLD; it never strips arbitrary digits/punctuation.

Media nodes keep refs, captions and provenance; no pixel payload/path is returned,
no generated caption, OCR, embedding or product inference. Hyperlinks use the
existing conservative Phase 4.1C safety rules, remain unresolved and are not
fetched. Only explicit tree relationships and HEADING_FOR edges are produced;
no cross-document authority, semantic relationship or second business classifier.

## 18. Bounds and security

Defaults, caller-lowerable only:

| Bound | Maximum |
| --- | ---: |
| Owned source | 20 MiB |
| PDF pages / page dimension | 50 / 1,440 points |
| Nodes / depth / edges | 10,000 / 32 / 20,000 |
| Table rows / columns / cells per table | 200 / 50 / 5,000 |
| Pictures | 100 |
| DOCX ZIP entries / expanded bytes | 1,000 / 80 MiB |
| DOCX image pixels | 20 million each / 40 million aggregate |
| Worker wall deadline / output | 120 seconds / 32 MiB |
| XML depth / elements per part | 80 / 100,000 |

Preflight rejects malformed/encrypted artifacts, ZIP traversal/duplicates,
oversized pages, external resources, XML entities, deep numbering and unsupported
media. PDF decompression ceiling is lowered, never relaxed, and restored after
preflight. Full DTO validation follows bounded mapping; no truncated-success mode.

A fresh worker has a narrow environment allowlist (no application DB/provider
credentials), offline model flags, denied socket/DNS/HTTP transport and denied
child execution audit hooks. Links and instruction-like text are data only.
Timeout kills the worker; resources and model/native memory die with it. Upstream
errors are reduced to safe typed categories, with stderr discarded.

**Limit:** Python network/audit guards and a process deadline are not an OS/native
sandbox or an RSS quota. Native parser vulnerabilities and transient allocation
remain upstream risks; production deployment would need an independently scoped
OS sandbox/resource policy. This slice does not claim production hostile-file
containment or accept arbitrary parser metadata from customers.

## 19. Separate frozen synthetic GOLD

`STRUCTURAL_GOLD_DOCLING_V1`, repository-authored CC0 content/diagram. The
manifest records bytes and SHA-256 for seven artifacts; `expected.json` contains
independently authored expectations, not reserialized adapter output.
Frozen expectations SHA-256:
`5b044dd539ad331d7b979643e4ebbad3daacad7d37d59b2837acfc17b32cd306`.

| Fixture | Bytes | Coverage |
| --- | ---: | --- |
| workshop.pdf | 5,215 | 2 pages, headings/body, numbered/bullet lists, table, Unicode, duplicates, image/caption, inert instructions |
| merged.pdf | 1,921 | Column-spanning table cell and header expectation |
| workshop.docx | 39,059 | Headings, nested lists, 2 tables/merged cell, explicit header, Unicode, link, image/caption |
| image_only.pdf | 3,237 | Explicit OCR-unavailable rejection |
| empty.pdf | 1,258 | Explicit empty/textless rejection |
| rotated.pdf | 3,649 | Frozen 90-degree source; explicit unsupported-rotation rejection |
| encrypted.pdf | 4,047 | Password/encryption rejection |

Fixture generation used reportlab 4.4.9 (BSD), python-docx 1.2.0 (MIT), pypdf
6.16.2 (BSD) and Pillow for the owned diagram. The builder is an explicit authoring
utility, not invoked by tests; PDF invariant metadata and fixed DOCX ZIP timestamps
are used. Encrypted bytes are frozen, not regenerated to chase a hash.

PDF skill: rendered and visually inspected all six unencrypted PDF pages. Empty
and rotated layouts were intentional. Documents skill: attempted DOCX rendering,
but the required LibreOffice executable is unavailable; visual DOCX pagination QA
is **not claimed**. OOXML checks and actual Docling DOCX conversion were completed.
The prior frozen GOLD and 23 saved Markdown website sources were not changed or
converted into synthetic PDFs to claim real-corpus validation.

Checkpoint audit correction: initially untracked ASCII-compatible PDFs were not
covered by `git diff --check`. Staging exposed PDF-format trailing whitespace
and Git's text/CRLF classification. Fixture-local binary attributes correct that
classification, not the PDF content. Staged blob hashes are checked against the
unchanged manifest; no artifact or expectation is regenerated.

## 20. Actual GOLD metrics

Precision/recall of independently annotated labels/blocks (N/A = empty denominator):

| Metric | workshop.pdf | workshop.docx | merged.pdf |
| --- | --- | --- | --- |
| Headings P/R | 1 / 1 (3/3) | 1 / 1 (3/3) | 1 / 1 (1/1) |
| Full list membership/order P/R | 1 / 1 (2/2) | 1 / 1 (3/3) | N/A |
| Table cells P/R | 1 / 1 (6/6) | 1 / 1 (9/9) | 1 / 1 (5/5) |
| Header P/R | 1 / 1 (2/2) | 1 / 1 (2/2) | N/A / 0 (0/1) |
| Exact text-block P/R | 18/19 = 0.9473684210526315 / 18/20 = 0.9 | 1 / 1 (24/24) | 1 / 1 (6/6) |
| Ordered concatenated text payload | exact | exact | exact |
| Link P/R | N/A | 1 / 1 (1/1) | N/A |
| Media retained | 1/1 | 1/1 | 0/0 |
| Nodes with parser-item provenance | 33/33 | 42/42 | 14/14 |
| Nodes with genuine PDF bbox | 24 | 0, intentional | 8 |
| Repeated extraction canonical equality | PASS | PASS | PASS |

PDF text-block metric is not 100%: Docling groups the Café sentence and first
Repeated notice into one block. Both occurrences survive, with distinct refs, and
the concatenated reading-order payload matches exactly. The extracted bullet
glyph is a replacement character from upstream; its declared list marker and item
semantics are retained, not repaired with guessed source bytes.

`merged.pdf` exposes a genuine upstream header miss: Access text and colspan=2
survive, but Docling did not label it as a header. The adapter does not infer that
role solely from position or alter GOLD to manufacture a pass.

Hierarchy checks verify valid rooted parent trees, heading-before-section order,
explicit heading edges and nested DOCX list relationships. These are scoped
fixture assertions, not an exhaustive independent layout-tree precision/recall
benchmark. PDF pages {1,2}, origin conversion and nonfabricated DOCX provenance
have separate assertions. No OCR accuracy score is claimed.

## 21. Differential information loss

Actual Core extraction → DTO comparison:

| Fixture | Original text items retained | Actual cells retained | Missing original item refs |
| --- | ---: | ---: | ---: |
| workshop.pdf | 13/13, P/R 1/1 | 6/6, P/R 1/1 | 0 |
| workshop.docx | 15/15, P/R 1/1 | 9/9, P/R 1/1 | 0 |
| merged.pdf | 1/1, P/R 1/1 | 5/5, P/R 1/1 | 0 |

No text/cell/ref loss in this tested mapping. Synthetic wrapper/row/cell nodes
increase node count; they are not claimed to be extra source observations. A
negative metric test removes DTO cells and verifies GOLD recall falls, ensuring
this is not merely a self-roundtrip test. Canonical DTO JSON also round-trips
through the frozen schema with source ownership intact.

## 22. Local performance

Final measurements below were run sequentially after tests completed, without
concurrent validation workers. Each conversion uses a fresh child, pinned CPU
models and two threads. Setup is
separated using public `initialize_pipeline`; conversion means models initialized,
not a long-running production parser pool. RSS is Windows peak working set.

| Fixture | Cold imports/preflight/model setup (s) | Initialized parse/export (s) | Worker elapsed (s) | Peak RSS (MiB) | Nodes / tables | OCR |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| workshop.pdf, 2 pages | 7.691996 | 3.792866 | 11.484862 | 1101.171875 | 33 / 1 | No |
| workshop.docx | 4.703311 | 0.091672 | 4.794983 | 396.281250 | 42 / 2 | No |
| merged.pdf, 1 page | 7.611263 | 3.345611 | 10.956875 | 1044.382813 | 14 / 1 | No |

Initialized PDF throughput: **0.527306 pages/s** (workshop) and **0.298899
pages/s** (merged table). Setup includes input/model hash checks; worker elapsed
excludes parent process launch/DTO construction/child exit and final JSON delivery.
Parse/export above is derived as worker elapsed minus setup to use one consistent
end timestamp. The raw `conversion_seconds` field additionally includes RSS
sampling overhead (notably about 12 ms on DOCX); it is not used to inflate the
throughput result. No production latency or hardware-sizing claim.

Local models occupy 366.62 MiB; cold Python/native libraries materially increase
RSS beyond model bytes. No persistent converter pool or memory optimization was
implemented. Each fixture was extracted twice and produced identical canonical
DTO JSON, independent of timing/RSS metadata. Final aggregate observations are
in ignored `.codex_structural_4_1d/evaluation.json`; no customer data is present.

## 23–24. Final validation

- Final focused 4.1D + 4.1C + 4.1A + 4.1B offline suites:
  **388/388 PASS, 48.742 s** = 92 new tests + 296 existing structural tests.
- Relevant existing guarded upload/exact-page-ingestion/tenant-security tests:
  **32/32 PASS, 2.080 s**. No lifecycle suite that calls `init_db()` was run.
  The existing local Redis-unavailable fallback was exercised; no DB/provider call.
- AST: **6/6 Python files PASS**. Parent adapter and worker module imports do
  not import Docling, ORM/database, retrieval or provider clients.
- Fixture bytes/hashes **7/7 PASS**; local model hashes **5/5 PASS**.
- Optional dependency consistency: `pip check` **PASS**.
- Secret-pattern scan across new/changed text files: **0 matches**.
- `git diff --check` and additional new-file trailing-whitespace scan: **PASS**.
- Existing frozen GOLD unchanged. Diff contains no live-ingestion, repository,
  schema, retrieval, credentials, customer corpus or application-config changes.

Complete canonical suite: **2,471/2,471 PASS, 308.670 s**, all existing **2,379**
plus **92** new tests. The expected Redis-unavailable messages in this run came
from the explicit socket/DNS deny guard, not an actual Redis connection. No
runtime change followed this passing run.

Earlier development
checks found and corrected mixed-list mode mapping, DOCX header assumptions,
required OpenCV extra, child USERPROFILE setup and the subprocess audit approach.
Fixture bytes/expected GOLD were not rewritten to hide those issues.

An initial extra-strict socket wrapper caused **11 Windows asyncio self-pipe
errors (2,471 tests, 316.559 s)**. Diagnosis: Python's Windows `socketpair()` uses
an internal loopback connection; a blanket connect-deny wrapper blocked it.
This was a validation-wrapper error, not an application regression. The rerun
permits only the thread-local stdlib socketpair operation while still rejecting
all external connects/DNS. No application/test expectation was weakened.

Reproduction commands from `backend` after deliberately installing the optional
requirements and provisioning the five exact model files:

```text
.venv/Scripts/python.exe -B -W ignore::DeprecationWarning -m unittest test_structural_docling_adapter test_structural_text_adapter test_structural_contracts test_structural_repository
.venv/Scripts/python.exe -B -W ignore::DeprecationWarning scripts/test_scoped_rag_regressions.py
.venv/Scripts/python.exe -B scripts/evaluate_structural_docling_adapter.py --models ../.codex_structural_4_1d/models --output ../.codex_structural_4_1d/evaluation.json
```

The canonical script was invoked through an in-memory `runpy` wrapper adding the
above external-socket guard. Its own existing configured-DB and HTTP/provider
patches remain intact. Parser children have their own independent offline guards.
No generated test/environment/model files were staged or committed.

## 25. Limitations

- Offline adapter only; no production upload or DB/RAG acceptance implied.
- No OCR; wholly or partially textless PDFs visibly fail. Rotated PDFs visibly fail.
- PDF merged-header miss and text-block grouping difference are measured above.
- Local learned layout/table extraction is not perfect source truth; UNKNOWN
  quality/manual_review is intentional. No commercial or medical meaning inferred.
- No native DOCX chart/vector/OLE/macro support or external resource fetch.
- DOCX complex table/header association can conservatively fail; no positional
  guess is allowed. DOCX layout-only 1x1 table flattening is upstream behavior.
- No DOCX visual pagination verification without LibreOffice; no PDF coordinates
  fabricated for DOCX. Hyperlinks only where the backend exposes them.
- Bounds/deadline are not an OS sandbox or hard native RSS ceiling.
- Exact repeat hashes are verified for the pinned local environment, not promised
  across other hardware, dependency versions, languages or complex layouts.
- Optional dependencies and the five verified model files must be deliberately
  provisioned before rerunning this suite; missing artifacts fail, not skip.
- Small synthetic fixtures only; no production sizing/throughput, scan quality,
  real-customer PDF/DOCX or broad multilingual extraction claim.

## 26. Next slice and scope confirmation

Next: separately authorized Phase 4 extraction/serializer work following the
design. No live ingestion hook, repository persistence, source activation,
structural chunk generation, embedding or retrieval integration is enabled here.

No customer/application database connected; no SQL/migration/fixtures executed
against PostgreSQL; no provider/model API calls; no crawl/reingestion/re-embedding;
no bot configuration or credential change; no production/Railway action; no push
or deployment. Deliberate dependency/source/model provisioning downloads were
setup only, not request-time parser downloads. Only Phase 4.1C was committed.

## Verdict

**PHASE 4.1C CHECKPOINT — COMMITTED**

`6017dcdc1b87c0023c240c7f253f0a4e69a6e2a3`

**PHASE 4.1D — COMPLETE**

**ISOLATED DOCLING PDF/DOCX STRUCTURAL ADAPTER VERIFIED**

**PDF/DOCX STRUCTURAL GOLD FROZEN**

**READY FOR NEXT PHASE 4 SLICE**

These verdicts cover the isolated, explicitly bounded adapter and measured
fixtures—not perfect upstream extraction or production readiness. Header recall,
OCR/rotation/complex-format restrictions and DOCX visual QA limitations remain
as reported. Phase 4.1D is uncommitted for review; HEAD remains the 4.1C checkpoint.
