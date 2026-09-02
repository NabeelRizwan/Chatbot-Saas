# First Customer Pilot Checklist

Do not mark an item complete from configuration alone; verify the behavior in the production pilot environment.

- [ ] Production Backend, Worker, and Frontend deployed from the same approved commit
- [ ] PostgreSQL healthy, migration head current, backup and restore tested
- [ ] Redis healthy and production readiness fails when it is unavailable
- [ ] ARQ Worker healthy and heartbeat visible
- [ ] Private S3-compatible Storage Bucket healthy from both Backend and Worker
- [ ] Stable JWT and credential-encryption secrets stored outside source control
- [ ] Gemini generation/embedding credentials verified for bots that use them
- [ ] Any optional provider credential profiles assigned only to matching-provider bots
- [ ] Firecrawl credentials and paid-page quota verified
- [ ] Controlled 100-page crawl limits and depth configured
- [ ] Crawl completed through normal ARQ lifecycle
- [ ] Crawl coverage, canonical URLs, duplicates, skips, failures, metadata, and useful content reviewed
- [ ] Exact-page mode verified not to ingest child pages
- [ ] PDF upload, restart durability, extraction, and retrieval tested
- [ ] TXT upload, restart durability, extraction, and retrieval tested
- [ ] DOCX upload, restart durability, extraction, and retrieval tested
- [ ] 15–20 representative customer questions tested
- [ ] Same-chat follow-up/entity memory tested
- [ ] Unknown/unsupported question tested for honest uncertainty
- [ ] Source URLs and CTA links tested
- [ ] Dashboard chat streaming and latency checked
- [ ] External widget session, streaming, sources, safe Markdown, and links tested
- [ ] WordPress generic script embed installed; no plugin or secret added
- [ ] Exact production CORS/auth origins and bot origin allowlist configured
- [ ] Password change/session rotation and logout-all tested
- [ ] Provider, crawl, queue, storage, DB, and chat logs/alerts monitored during pilot
- [ ] Rollback owner, escalation contact, and maintenance window agreed
