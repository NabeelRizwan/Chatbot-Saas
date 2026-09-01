import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const root = path.resolve(import.meta.dirname, "..");
const source = fs.readFileSync(path.join(root, "lib", "knowledge-contract.ts"), "utf8");
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const module = { exports: {} };
new Function("exports", "module", output)(module.exports, module);
const { isKnowledgeJobActive, normalizeKnowledgeJob } = module.exports;

assert.equal(isKnowledgeJobActive("processing"), true);
assert.equal(isKnowledgeJobActive("cancelling"), true);
for (const terminal of ["ready", "failed", "cancelled"]) assert.equal(isKnowledgeJobActive(terminal), false);

const fixture = normalizeKnowledgeJob({
  job_id: "job_contract", bot_id: 7, source_name: "Docs", source_url: "https://example.com/docs",
  ingestion_type: "website", status: "failed", stage: "failed", attempt_number: 2, retryable: true,
  cancellable: false, created_at: "2026-08-21T00:00:00", error_code: "TIMEOUT", error_message: "Safe timeout",
  active_version: 3, candidate_version: 4, version_state: "failed", chunks_created: 8,
  crawl_coverage: { discovered: 10, eligible: 8, crawled: 7, indexed: 6, skipped: 1, failed: 1,
    duplicates: 1, maximum_depth: 2, coverage_percent: 75, documents: 6, chunks: 8,
    url_results: [{ url: "https://example.com/broken", result: "failed", reason: "Page crawl failed" }] },
});
assert.equal(fixture.botId, "7");
assert.equal(fixture.crawlCoverage.indexed, 6);
assert.equal(fixture.crawlCoverage.urlResults[0].reason, "Page crawl failed");
assert.equal(fixture.activeVersion, 3);

const ui = fs.readFileSync(path.join(root, "components", "knowledge", "knowledge-bot-client.tsx"), "utf8");
for (const truthfulCopy of ["Cancelling…", "Ready for chatbot answers.", "Retry", "Crawl coverage", "previous knowledge remains active", "Active version"]) {
  assert.ok(ui.includes(truthfulCopy), `missing UI contract: ${truthfulCopy}`);
}
assert.ok(ui.includes("job.cancellable"));
assert.ok(ui.includes("job.retryable"));
assert.ok(ui.includes("window.confirm"));
