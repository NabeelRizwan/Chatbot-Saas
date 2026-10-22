CLEAN OG DEPLOYED LOCAL — isolated cleanup candidate
Base: e8557f4f6624b53ea3f1afe18b150074aa7c16e5 (last recorded deployed release)
Prepared: 22 October 2026. Nothing was pushed or deployed.

PURPOSE
This is the original application's cleanup candidate, not RAG2 and not a new
answer method. Accounts, organizations, bots, knowledge data structures,
retrieval/ranking, answer prompts, widget transport, and migrations are retained.
The original Chatbot-Saas checkout and the three earlier prepared variants were
not edited. Live Railway state was not queried or changed.

ROLLBACK
../rollback-deployed-e8557f4-20261022/ contains the exact 1,081-file source snapshot,
source ZIP, per-file SHA-256 manifest, commit identity and restore instructions.
It is a SOURCE rollback. It is not a database, object-storage or secret backup.
No production data/schema was changed. Read README-ROLLBACK.md in that folder.

CHANGES
* Removed eight unreferenced obsolete backend files, including the one-off
  tenant-specific repair script. Shared RAG helpers and migrations remain.
* Removed two unused frontend components and two unused direct dependencies.
* Moved optional browser/test dependencies out of the production requirements.
  HTML extraction remains available without importing Playwright.
* Uses Next standalone runtime packaging instead of copying all build tooling
  into the frontend runtime image.
* Hides settings that only stored a value without implementing the advertised
  language/notification/general-knowledge behavior; existing saved values remain.
* Corrects read-only role labels and two misleading old UI messages.
* Fixes middleware registration so browsers can read rate-limit responses and
  preflight requests do not consume ordinary request quota. Limits remain intact.
* Fixes knowledge-page layout overflow on narrow screens. Document actions and
  long filenames fit a 390-pixel viewport; desktop layout was also checked.
* Corrects an old test's expected migration head and revision count to match the
  migrations already in the deployed release. No migration/schema file changed.
* Refreshes the visible login-session list after a successful password change;
  the existing server-side session revocation behavior is unchanged.
* Adds the user-requested, provider-listed Gemini 3.8 Flash model option to
  backend validation and the bot editor. Existing models and default stay intact;
  this does not change retrieval, ranking, prompts or generation implementation.
* Corrects temporary-failure messages to distinguish AI generation failures from
  knowledge retrieval failures. HTTP status, quota release, retries, generation
  prompts and RAG algorithms remain unchanged.

WHAT WAS DELIBERATELY KEPT
Shared legacy RAG helpers, alternate engine adapters, schemas, migrations,
licenses, tests and rollback support cannot safely be classified as disposable
from their names alone. Normal production image exclusions still omit tests,
reports, local databases, secrets and development caches.

LOCAL ACCEPTANCE ONLY
Start-Local.ps1 / Stop-Local.ps1 control only Compose project
chatbot-clean-og-local-20261022 with separate databases, volumes and network.
Frontend: http://localhost:3104   API: http://localhost:8104
Local S3 ports: 9104 / 9204. Postgres/Redis/retrieval have no public host ports.
The local environment uses HTTP development cookies and must not be copied to
Railway. .env.local is private and excluded from Git and deployment archives.
The local object store is pinned Silo, a compatible maintained MinIO fork, because
the old MinIO image references could not be downloaded in this environment. Production object
storage settings and manifests were not replaced.
Upload allowance is 100/hour only for loading the 48 saved test sources. The
production default is still 20/hour. The local Gemini admission budget is
20 calls/day for this acceptance run, not a statement of universal provider quota.
The local ingestion worker is configured for one job at a time because this
stack has one retrieval inference lane. The initial 48-file burst with the
original ten-job default exposed existing admission timeouts; the report keeps
those failures and the subsequent sequential recovery. This is not a change to
chat concurrency or the deployed RAG/ranker.
The recorded deployed answer flags are native messages OFF, structured output
OFF, citation normalization ON. Local acceptance uses those recorded flags.
Website and model credentials were configured only in this isolated environment.

VALIDATION AND LIMITATIONS
See ../clean-og-audit/REPORT.html and its linked evidence for the final results.
The 190 saved-answer replay checks deterministic prompt/postprocessing parity;
it is not 190 fresh Gemini calls. Gemini 3.8 was attempted through the app and
returned generation failures despite successful retrieval. Separate one-word
provider diagnostics also returned HTTP 504, including with a 60-second limit.
The report separately records the normal Gemini 3.5 Flash-Lite acceptance run.
Fresh testing uses real upload ingestion; historical answers used saved website
metadata, so answer differences cannot be attributed solely to this cleanup.
The local stack uses inline chat execution; optional Hatchet delivery was tested
offline, not as a live Railway multi-worker load test.
Team invitation acceptance/delivery and payment-provider checkout remain earlier
unfinished product work. Appointment/order connections still require a selected
business provider. Cleanup does not implement these deferred features.

DEPLOYMENT
Do not deploy deploy.local.yml or .env.local. A future approved rollout should
use the production manifests, intended runtime variables and secure credential
store, verify migrations, preserve the encryption key for existing encrypted
records, and retain the source rollback above. No deployment is authorized by
merely opening this folder. The final report states actual readiness and limits.
