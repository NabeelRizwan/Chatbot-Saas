# Full-port dependency and license audit

Pin: RAGFlow v0.27.2 `a024bea0cd93f39e6652a42bf84dd20c55bc560b`. This ledger is updated during integration; a dependency listed here is not evidence of a working subsystem.

| Package / exact pin | License | Pinned caller / reason | CPU/RAM/native requirements |
| --- | --- | --- | --- |
| langgraph 1.2.0; checkpoint 4.1.1; prebuilt 1.1.0; sdk 0.3.6 | MIT | agentic_rag_graph and action_session actual StateGraph execution | Python orchestration; bounded per-request state; no GPU |
| langchain-core 1.4.9 | MIT | action_session message reducers/native tool message conversion | Python; Pydantic/orjson wheels |
| networkx 3.6.1 | BSD-3-Clause | graph extractor/index/entity resolution | CPU in-memory graph; graph size must be bounded operationally |
| xxhash 3.6.0 | BSD-2-Clause | compiler stable artifact IDs | native wheel; negligible runtime memory |
| rapidfuzz 3.14.5 | MIT | upstream graph entity resolution | native CPU wheel |
| pandas 2.3.3 | BSD-3-Clause | DOCX/Excel tables, KG rendering/community reports | native NumPy dependency; bounded input bytes |
| openpyxl 3.1.5 | MIT | Excel parser | CPU; ZIP expansion/input bounds required |
| python-pptx 1.0.2 | MIT | PowerPoint parser | lxml/Pillow; CPU; ZIP expansion bounds |
| pypdf (existing 6.16.1) | BSD-3-Clause | extracted upstream PlainParser/outlines | CPU; no OCR/layout inference |
| python-docx (existing 1.2.0) | MIT | actual naive.Docx parser | lxml wheel; CPU |
| Pillow (existing environment) | HPND | lazy embedded image representation | native wheel; decompression/image bounds, no fetching |

Direct new versions are copied from pinned `uv.lock`, not floating upstream main. Existing embedding/reranker packages and weights remain unchanged. Installed distribution metadata and dependency resolution will be checked before runtime enablement.

## Not approved merely by inventory

- Upstream graspologic uses a specific fork commit `38e680cab72bc9fb68a7992c3bcc2d53b24e42fd`; do not silently replace it with PyPI graspologic. Leiden/node embedding remain unavailable until the exact fork and native closure are audited.
- DeepDoc ONNX OCR/layout/table assets and alternate GPU parser services are optional, not implicitly downloaded or provisioned.
- External OCR/vision/audio/web providers require explicit credentials and truthful capability status.
- No AGPL PDF replacement, product database, production secrets or second account system is introduced.

## Installed closure and licensing verification

Installed package metadata verified the above versions/licenses. Additional resolved transport/parser closure is pinned from the isolated tested environment (not represented as an upstream algorithm import): langsmith 0.13.0 MIT; orjson 3.12.0 MPL-2.0 AND (Apache-2.0 OR MIT); ormsgpack 1.12.2 Apache-2.0 OR MIT; zstandard 0.25.0 BSD-3-Clause; uuid-utils 0.17.1 BSD-3-Clause; requests-toolbelt 1.0.0 Apache-2.0; et-xmlfile 2.0.0 MIT; xlsxwriter 3.2.9 BSD-2-Clause. These are ordinary unmodified distribution dependencies, not copied project source. Binary wheels are required for the Rust/C serialization/compression helpers; no GPU. LangSmith telemetry is disabled, so its SDK does not constitute use of the hosted service. Existing platform dependencies are not changed.

The offline test runner adds pytest-asyncio 1.3.0 (Apache-2.0), exactly the pinned upstream test dependency. Four upstream async tests initially could not execute until this isolated test extra was installed; all 95 newly copied upstream parity cases then passed.

Microsoft GraphRAG-derived files retain their MIT notices and the complete `third_party/ragflow/MICROSOFT_GRAPHRAG_LICENSE`. LightRAG/MiniRAG-derived prompts retain MIT notices and `HKUDS_GRAPH_LICENSE`; the official [LightRAG license](https://raw.githubusercontent.com/HKUDS/LightRAG/main/LICENSE) and [MiniRAG license](https://raw.githubusercontent.com/HKUDS/MiniRAG/main/LICENSE) were checked for notice attribution only, not used as algorithm sources. RAGFlow source remains pinned to v0.27.2. MIT portions are labelled in the manifest, not mislabelled wholly Apache.

Copied/adapted RAGFlow code retains upstream attribution and source/destination hashes in the port manifest. Product/provider compatibility code is clearly distinguished from upstream algorithms. MPL-bearing unmodified dependency distribution does not relicense application source; no incompatible copied code was identified. This is a source/dependency audit, not a claim of legal advice or complete vulnerability certification.
