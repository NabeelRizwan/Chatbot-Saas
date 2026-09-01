import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const ui = fs.readFileSync(path.join(root, "components", "knowledge", "knowledge-bot-client.tsx"), "utf8");
const service = fs.readFileSync(path.join(root, "services", "knowledge-service.ts"), "utf8");
const store = fs.readFileSync(path.join(root, "store", "knowledge-store.ts"), "utf8");

assert.ok(ui.includes('useState<CrawlMode>("recursive")'), "recursive mode must remain the UI default");
assert.ok(ui.includes('<option value="recursive">This page + child pages</option>'));
assert.ok(ui.includes('<option value="single_page">This page only</option>'));
assert.ok(ui.includes("crawlWebsite(botId, url, crawlMode)"));
assert.ok(service.includes('crawlMode: CrawlMode = "recursive"'));
assert.ok(service.includes("crawl_mode: crawlMode"));
assert.ok(store.includes('crawlMode = "recursive"'));
