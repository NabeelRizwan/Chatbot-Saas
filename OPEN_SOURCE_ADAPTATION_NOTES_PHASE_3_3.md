# Phase 3.3 source-study ledger

Date: 2026-09-13. Design study only; no upstream code copied and no dependency added.

| Source | Revision / license | Inspected | Decision |
|---|---|---|---|
| [Snowball](https://github.com/snowballstem/snowball) | `5f0b93ea7353433231dd645a08a865156d27ae49`; BSD-3-Clause | Complete `algorithms/english.sbl` and `COPYING`; region marking, Steps 1a–5, exceptions, stem entry point | Do not copy or introduce a stemmer for identity resolution. |
| [Snowball English algorithm](https://snowballstem.org/algorithms/english/stemmer.html) | Documentation inspected at task time | Derivational suffix handling and exceptions | Simple suffix removal is not reliable identity evidence. |
| [PostgreSQL text-search dictionaries](https://www.postgresql.org/docs/current/textsearch-dictionaries.html) | Official current documentation | Simple versus Snowball normalization | Keep existing Resource FTS `simple`; do not change accepted proper-name semantics. |

The upstream implementation uses bounded regions and exceptions, not arbitrary suffix deletion. Even a correct shared stem would establish lexical similarity, not unique business identity. Verb/nominalization pairs therefore remain on existing bounded fuzzy/token discovery paths; no hard scope follows from morphology alone. An auxiliary English-stemming channel was considered and rejected for this narrow repair: it would need independent collision/recall validation and does not solve missing semantic or ordering evidence.

Original local changes only: anchored request-framing variants and diagnostic classification of candidate-backed lexical insufficiency. Existing original-identity priority, candidate limits, SQL channels, informative-evidence-5 policy, authorization and factual-evidence boundaries remain intact. No historical name/ID, synonym dictionary, NLTK/spaCy, provider call or new model is used.
