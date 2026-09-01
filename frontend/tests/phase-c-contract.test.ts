import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import {
  buildPublicChatCurl,
  buildWidgetScriptSnippet,
  resolveWidgetBaseUrl,
} from "../lib/deployment-contract.js";
import { buildSharedTranscriptUrl, fetchSharedTranscript } from "../lib/public-share.js";
import { summarizeSetupUploads } from "../lib/setup-status.js";
import {
  knowledgeFileAccept,
  supportedKnowledgeExtensions,
  validateKnowledgeFile,
} from "../lib/upload-contract.js";

async function main() {
  assert.equal(resolveWidgetBaseUrl("https://app.example/", "https://runtime.example"), "https://app.example");
  assert.equal(resolveWidgetBaseUrl(undefined, "https://runtime.example/"), "https://runtime.example");

  const widget = buildWidgetScriptSnippet("https://app.example/", "https://api.example/", "42");
  assert.match(widget, /src="https:\/\/app\.example\/widget\.js"/);
  assert.match(widget, /data-api-base-url="https:\/\/api\.example"/);
  assert.match(widget, /data-bot-id="42"/);
  assert.doesNotMatch(widget, /localhost|127\.0\.0\.1/);

  const curl = buildPublicChatCurl("https://api.example/", "42");
  assert.match(curl, /^curl -X POST https:\/\/api\.example\/public\/chat\/42/);
  assert.match(curl, /Content-Type: application\/json/);
  assert.match(curl, /'\{"message":"Hello assistant!"\}'/);
  assert.doesNotMatch(curl, /app\.example/);

  const frontendRoot = process.cwd();
  const builderSource = readFileSync(join(frontendRoot, "components/bots/advanced-bot-builder.tsx"), "utf8");
  assert.doesNotMatch(builderSource, /<iframe\s+src=/);
  assert.doesNotMatch(builderSource, /Copy Share Link/);
  assert.match(builderSource, /Hosted chat pages and iframe embeds are not available yet/);
  assert.doesNotMatch(builderSource, /window\.location\.origin[^\n]*\/public\/chat/);

  const dynamicSharePage = join(frontendRoot, "app/public/share/[token]/page.tsx");
  const malformedSharePage = join(frontendRoot, "app/public/share/%5Btoken%5D/page.tsx");
  assert.equal(existsSync(dynamicSharePage), true);
  assert.equal(existsSync(malformedSharePage), false);
  assert.match(readFileSync(dynamicSharePage, "utf8"), /useParams<\{ token: string \}>/);

  assert.equal(
    buildSharedTranscriptUrl("https://api.example/", "token with spaces"),
    "https://api.example/public/share/token%20with%20spaces",
  );
  let fetchedUrl = "";
  const transcript = await fetchSharedTranscript("https://api.example", "valid-token", async (input) => {
    fetchedUrl = String(input);
    return new Response(JSON.stringify({ session: { title: "Shared", bot_name: "Bot", created_at: "now" }, messages: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  assert.equal(fetchedUrl, "https://api.example/public/share/valid-token");
  assert.equal(transcript.session.title, "Shared");
  await assert.rejects(
    fetchSharedTranscript("https://api.example", "invalid", async () => new Response("not found", { status: 404 })),
    /not found or sharing has been disabled/,
  );
  assert.throws(() => buildSharedTranscriptUrl("https://api.example", ""), /invalid/);

  assert.deepEqual(supportedKnowledgeExtensions, [".pdf", ".txt", ".docx"]);
  for (const extension of [".pdf", ".txt", ".docx"]) assert.match(knowledgeFileAccept, new RegExp(`\\${extension}`));
  for (const extension of [".csv", ".xlsx", ".md"]) assert.doesNotMatch(knowledgeFileAccept, new RegExp(`\\${extension}`));
  assert.equal(validateKnowledgeFile({ name: "guide.pdf", size: 100 }), null);
  assert.equal(validateKnowledgeFile({ name: "notes.txt", size: 100 }), null);
  assert.equal(validateKnowledgeFile({ name: "manual.docx", size: 100 }), null);
  for (const filename of ["data.csv", "sheet.xlsx", "readme.md"]) {
    assert.match(validateKnowledgeFile({ name: filename, size: 100 }) ?? "", /PDF, TXT, and DOCX/);
  }

  assert.equal(summarizeSetupUploads(0, 0).title, "Bot created");
  const processing = summarizeSetupUploads(2, 0);
  assert.match(processing.title, /knowledge processing/);
  assert.doesNotMatch(processing.description, /complete|ready/i);
  const partial = summarizeSetupUploads(3, 1);
  assert.equal(partial.variant, "error");
  assert.match(partial.description, /1 rejected/);
  const failed = summarizeSetupUploads(2, 2);
  assert.equal(failed.variant, "error");
  assert.match(failed.title, /uploads failed/);

  console.log("Phase C frontend deployment/share/upload contract tests passed");
}

void main();
