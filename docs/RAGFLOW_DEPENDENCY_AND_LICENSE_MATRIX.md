# Dependency and license matrix

## Completeness expansion dependencies (2026-09-21)

| Dependency | Version | License | Purpose |
| --- | --- | --- | --- |
| Jinja2 | 3.1.6 | BSD-3-Clause | Actual upstream SandboxedEnvironment prompts; pinned uv.lock version |
| json-repair | 0.60.1 | MIT | Actual model JSON parsing/retry; pinned uv.lock version |
| MarkupSafe | 3.0.3 installed transitive | BSD-3-Clause | Jinja2 dependency |

New RAGFlow Python, prompts and tests remain Apache-2.0 with attribution. Existing numpy/NLTK/tiktoken/CPU models reused. No new model weights, external generation provider dependency or credential. Optional agentic/graph/RAPTOR executors are not silently enabled.

## Gate and attribution

The pinned RAGFlow root LICENSE and retained Python headers identify Apache-2.0. The exact LICENSE is included; our NOTICE describes the source and modifications and does not invent an upstream NOTICE. Source/data hashes and copied versus adapted distinctions are in the manifest. No upstream product frontend, binary model weights or opaque OCR binaries were copied.

This is an engineering attribution review, not legal clearance for a future hosted search product. No incompatible code was identified in the vendored RAGFlow subset. Third-party licenses are not all Apache: LGPL dependencies and the Elasticsearch service need their own compliance obligations. No blanket production/commercial-distribution approval is claimed.

The optional service is Elasticsearch 8.11.3. Its [official versioned license](https://github.com/elastic/elasticsearch/blob/v8.11.3/LICENSE.txt) is not Apache-only. [Elastic License 2.0](https://github.com/elastic/elasticsearch/blob/v8.11.3/licenses/ELASTIC-LICENSE-2.0.txt) restricts offering substantial Elasticsearch functionality as a hosted/managed service and requires retained notices. Here ES is an unexposed local internal development dependency, not copied into our source. Obtain deployment/distribution review before offering search service functionality to customers. Do not silently substitute OpenSearch and claim identical retrieval.

## Direct optional environment

Versions are declared in backend/requirements-ragflow.txt. Required means required for the selected optional engine, not for the existing platform. Resource estimates are rough package/runtime orders of magnitude, not measurements.

| Package/version | Upstream use / reason | License | Required/optional | CPU/RAM; disk impact | External service? / existing substitute / decision |
| --- | --- | --- | --- | --- | --- |
| infinity-sdk 0.7.3 | rag/nlp/rag_tokenizer.py native tokenizer/frequency trie | Apache-2.0 SDK; dependency/asset licenses separate | Required native tokenizer | CPU trie/tokenization, tens+ MiB; wheel 29.7 MB plus large SDK dependencies | No Infinity server; old tokenizer not equivalent; WRAP |
| elasticsearch 8.19.3 | rag/utils/es_conn.py client | Apache-2.0 | Required ES path | Small client; low memory, MB-scale | Local ES service; PostgreSQL not equivalent; KEEP dependency |
| elasticsearch-dsl 8.12.0 | Actual upstream search expression construction | Apache-2.0 | Required | Low CPU/RAM, MB-scale | Same ES; no rewrite |
| elastic-transport 8.19.0 | ES connection transport; installed LICENSE inspected | Apache-2.0 | Required | Connection buffers, MB-scale | Same ES; explicit local URL only |
| Markdown 3.8.2 | deepdoc/parser/markdown_parser.py | BSD-3-Clause | Required | Linear text work, small package | None; retain upstream parser |
| beautifulsoup4 4.13.5 | deepdoc/parser/html_parser.py structure | MIT | Required HTML | Memory proportional to DOM, small package | None; preserve parser |
| chardet 5.2.0 | Upstream HTML encoding helper | LGPL (package metadata) | Required import | CPU encoding detect, small package | None; unmodified external dependency, retain notices/license when redistributed |
| numpy 1.26.4 | Embedding vectors/rerank; SDK requires <2 | BSD-3-Clause + bundled numerical notices | Required | Vector arrays; tens of MB | None; existing version differs, separate venv |
| scipy 1.17.1 | sklearn numeric dependency | BSD-3-Clause + bundled notices | Required transitive | Numerical runtime; tens+ MB | None; separate environment |
| scikit-learn 1.7.2 | query.py cosine/hybrid similarity | BSD-3-Clause | Required | CPU vector comparison; tens+ MB | None; retain upstream numeric behavior |
| nltk 3.10.3 | SDK/tokenizer and WordNet synonyms | Apache-2.0 library; corpus terms separate | Required native path | Token/corpus memory, separate resource disk | No server; do not auto-download resources |
| tiktoken 0.14.0 | token budget/truncation | MIT | Required native path | CPU tokenization, cached encoding asset | No model call; prepare cache to avoid first-use download |
| python-docx 1.2.0 | Our ordered DOCX extraction wrapper | MIT | Optional format | DOM/XML memory; small package plus lxml | None; WRAP instead of full DeepDoc layout |
| pypdf 6.16.1 | Our plain PDF text extraction wrapper | BSD-3-Clause | Optional format | CPU/pages; MB-scale package, input-dependent memory | None; no OCR parity claimed |
| pytest 8.4.2 | Ported/new offline tests | MIT | Test only | Test fixtures; small package | None; never runtime model |

## Important transitives and assets

These are external packages, not vendored source. SDK constraints below are read from the downloaded official 0.7.3 wheel metadata; the failed full install did not produce a complete platform-independent lock. Record exact resolved versions in a clean native validation environment before distribution.

| Dependency / version or constraint | Parent / purpose | License / risk | Required / resource impact / decision |
| --- | --- | --- | --- |
| datrie >=0.8.3,<0.9 (attempted 0.8.3) | SDK tokenizer trie | LGPL; native extension | Required native; Windows C++ build blocked; no compiler installed |
| readerwriterlock >=1,<2 | SDK tokenizer locks | BSD-style package; verify final distribution notice | Required SDK; small; not copied |
| hanziconv >=0.3,<0.4 | Traditional/simplified conversion | MIT package; preserve notices | Required SDK; small data; not copied |
| sqlglot[rs] >=27.10 | SDK SQL/API package dependencies, not used as our retriever | MIT package, optional native extra license review on distribution | SDK install closure; no SQL service used |
| pydantic >=2.9,<3; thrift >=0.20,<1 | SDK typed/wire contracts | MIT; Apache-2.0 | SDK closure; no Infinity server |
| pandas >=2.2,<3; pyarrow >=21,<23; polars-lts-cpu >=1.9,<2 | SDK dataframe/binary API closure | BSD-3-Clause; Apache-2.0; MIT (plus bundled notices) | Large binary dependencies; no dataframe search replacement |
| setuptools >=78.1.1,<81 | SDK package/build | MIT | Build/install only |
| lxml 6.1.1 observed | python-docx XML | BSD-3-Clause; bundled libxml/libxslt notices | Optional DOCX; binary package, CPU/XML |
| joblib 1.6.0, threadpoolctl 3.7.0 observed | sklearn execution/numeric thread control | BSD-3-Clause | Required numeric closure; modest |
| soupsieve 2.9.2 observed | BeautifulSoup selectors | MIT | Required HTML closure; small |
| python-dateutil 2.9.0.post0 observed | ES DSL / SDK dates | Apache-2.0/BSD dual | Small; not copied |
| urllib3 2.8.0, requests 2.34.2 observed | HTTP transports | MIT; Apache-2.0 | Connection buffers; no automatic provider use |
| certifi 2026.7.22 observed | HTTP CA bundle | MPL-2.0 | Bundle redistribution notice required |
| regex 2026.9.10 observed | tiktoken/NLTK token patterns | Apache-2.0 AND CNRI-Python | Native package; no parser substitution |
| packaging 26.3, iniconfig 2.3.0, pluggy 1.6.0 observed | Test/tool dependency closure | Apache-2.0 OR BSD-2-Clause; MIT; MIT | Test/tool only; small |
| SDK huqie dictionaries; NLTK WordNet/punkt resources | Native lexical behavior | Inspect bundled/individual data notices before redistributing assets; not assumed Apache because SDK is | Native setup prerequisite; no model/corpus download performed here |
| rag/res/ner.json, synonym.json | Pinned term/synonym resources | Pinned repository Apache attribution, no separate header found in these JSON files | Actually copied, immutable hash tracked |
| Embedding / learned reranker / OCR weights | Operator-selected models | NOT SELECTED; license depends on model/provider | No downloads/calls; must be reviewed when chosen |

Observed tests used inherited NumPy 2.3.5 / installed SciPy 1.18.1 and reused platform NLTK metadata. The optional full dependency manifest was not successfully installed because of datrie. This is a native-environment validation limitation, not proof the pinned optional stack passes.

No paid service, GPU, Redis, MinIO, MySQL, production database or Railway change is required by the isolated fixture smoke. Elasticsearch native tests and model licensing/configuration remain separate gates.
