# Organisation knowledge pipelines

Accounts, memberships, bots, documents, billing and conversation history remain in
the existing SaaS application. The two existing retrieval services each support
both profiles. No extra customer-facing application or database is required.

## Platform admin control

The platform admin's Organisations page selects `RAG2 Improved` or `OG` for each
organisation. An organisation owner, customer, widget visitor or API caller
cannot select the pipeline. The backend resolves the stored policy and rejects
customer access to the admin endpoint, including forged frontend flags.

`GET /admin/organizations/{id}/knowledge-pipeline` returns the current selection
and revision. `PATCH` requires both the desired selection and the exact expected
selection/revision. A stale edit returns 409. Successful changes create an audit
record. A turn accepted before a change keeps its accepted pipeline; the next
turn uses the new policy. Old queued payloads without this field remain OG.

The additive migration backfills existing organisations to OG for a staged
rollout. New organisations default to RAG2 Improved. Activate existing
organisations through the same audited admin endpoint after the release checks.

## Answer behavior

OG retains its existing retrieval, ranking and answer method. RAG2 Improved adds
focused search planning, the prepared RAG2 context selection and Voyage reranking,
with a maximum planned evidence budget of 48,000 tokens. The actual available
context can be smaller. All evidence is checked against current authorised
documents before generation and delivery.

For Gemini 3.5 Flash-Lite, RAG2 uses the tested source-map answer method with medium
thinking. The source map stays private; customers see the final answer. Other
configured providers/models keep their existing answer protocol while using RAG2
retrieval. Customer bot instructions remain in effect. Neither source validation
nor a larger context guarantees that every model answer is correct or complete.

RAG2 generation has its own 150-second allowance. OG retains its configured
30-second generation/retry allowance and 20-second Gemini transport cap. A
shorter remaining whole-turn lifetime always takes precedence. RAG2 public,
playground and API turns require the existing Hatchet execution service.

## Capacity and rollout

Keep the current two retrieval services. Each loads one model runtime and has
separate OG/RAG2 corpus caches and admission. Voyage waits release the shared
local inference lock, but local CPU work and the Hatchet worker pool are still
shared. This is not a promise of unlimited parallel replies or zero contention.

Configure both retrieval services with the same Voyage credential, shared Redis
URL and stable account identifier. Default account limits are 3 requests and
10,000 tokens per 62-second rolling window. Raising them requires verified
provider allowance and the explicit configuration flag described in
[the retrieval runbook](../deploy/llama-retrieval/DUAL_PIPELINE.md).

Free limits can make a reply take minutes or exceed bounded queue/turn deadlines.
Readiness checks configuration and Redis without spending a provider request;
actual provider access must be checked separately. RAG2 failures do not silently
switch a customer's turn to OG. An admin can choose OG for subsequent turns.

Deploy the compatible retrieval services first, apply the additive migration,
deploy compatible workers, then the backend and frontend. Preserve the exact
source/configuration and a database backup before rollout. Advancing the migration
head makes the still-running old backend report outdated migrations until its
compatible replacement starts; allow for this transition window.

For immediate rollback, select OG through the admin API while keeping the new
compatible release running. Accepted turns retain their captured policy and finish
with it. Original Clean OG commit `f8b5a37` cannot start against the new migration
head. Prepared compatibility commit `cff9c6e`, on branch
`rollback/clean-og-routing-schema-20261023`, contains that original application plus
only the additive migration file so its startup check accepts `20261023_01`.

Before reverting to those old workers, quiesce new turn admission and drain **all**
accepted turns and saved-question cases using the new payload format, including OG
turns. Old workers reject its added fields. Also assess retained Redis payloads and
Hatchet redelivery: a terminal job can still be addressed by a status check, retry
or delayed delivery after active work finishes. Verify their expiry or a separately
rehearsed compatibility procedure before reverting; draining RAG2 alone is not
sufficient. Preserve saved results and history. Retain the additive columns and
migration head, and never restore an old database merely to revert code and erase
newer data. Review organisation policies again before a later roll-forward because
the retained server default for new organisations remains RAG2 Improved.
