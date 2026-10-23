import assert from "node:assert/strict";
import console from "node:console";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

// Exercise the real service against in-memory streams: no server or provider.
const source = fs.readFileSync(path.resolve(import.meta.dirname, "../services/chat-service.ts"), "utf8");
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const module = { exports: {} };
new Function("exports", "module", "require", output)(module.exports, module, () => ({ API_BASE_URL: "https://mock.invalid", request: () => { throw new Error("Unexpected fallback"); } }));
const { streamChatMessage, ChatStreamUnsupportedError } = module.exports;
const originalFetch = globalThis.fetch;
const options = { botId: "9", message: "Synthetic question", onToken: () => {} };
const frame = (value) => `data: ${JSON.stringify(value)}\n\n`;
const encoder = new globalThis.TextEncoder();
let checks = 0;

try {
  const chunks = [": keepalive\r", "\n\r\n", frame({ type: "meta", queued: true, buffered: true }), frame({ type: "status" }),
    frame({ source_map: "private data is not answer text" }), frame({ token: "Approved answer." }), frame({ sources: [{ document_id: 4, filename: "Original page", title: "Public guide", citation_index: 7, source_url: "https://library.example/guide" }] }), 'data: {"done":true}'];
  globalThis.fetch = async () => new globalThis.Response(new globalThis.ReadableStream({ pull(controller) { const chunk = chunks.shift(); if (chunk === undefined) controller.close(); else controller.enqueue(encoder.encode(chunk)); } }));
  const tokens = []; const statuses = [];
  const result = await streamChatMessage({ ...options, onToken: (token) => tokens.push(token), onStatus: (status) => statuses.push(status) });
  assert.deepEqual(tokens, ["Approved answer."]);
  assert.deepEqual(statuses, ["queued", "running"]);
  assert.equal(result.sources[0].documentId, "4");
  assert.equal(result.sources[0].title, "Public guide");
  assert.equal(result.sources[0].citationIndex, 7);
  assert.equal(result.sources[0].sourceUrl, "https://library.example/guide");
  checks++;

  for (const body of [frame({ token: "Partial" }), frame({ type: "error", message: "Rejected" }), "event: error\ndata: {\"detail\":\"Rejected\"}\n\n"]) {
    globalThis.fetch = async () => new globalThis.Response(body);
    await assert.rejects(streamChatMessage(options), (error) => !(error instanceof ChatStreamUnsupportedError));
    checks++;
  }
  for (const status of [404, 405, 403, 503]) {
    globalThis.fetch = async () => new globalThis.Response("", { status });
    await assert.rejects(streamChatMessage(options), (error) => (error instanceof ChatStreamUnsupportedError) === [404, 405].includes(status));
    checks++;
  }
  globalThis.fetch = async () => { throw new TypeError("Connection lost after request may have been sent"); };
  await assert.rejects(streamChatMessage(options), (error) => !(error instanceof ChatStreamUnsupportedError));
  checks++;

  const abort = new globalThis.AbortController();
  let started;
  const accepted = new Promise((resolve) => { started = resolve; });
  globalThis.fetch = async (_url, init) => new globalThis.Response(new globalThis.ReadableStream({ start(controller) {
    assert.equal(init.signal, abort.signal);
    init.signal.addEventListener("abort", () => controller.error(new globalThis.DOMException("Stopped", "AbortError")), { once: true });
    controller.enqueue(encoder.encode(": keepalive\n\n"));
    started();
  } }));
  const pending = streamChatMessage({ ...options, signal: abort.signal });
  await accepted;
  abort.abort();
  await assert.rejects(pending, (error) => error.name === "AbortError");
  checks++;
  console.log(JSON.stringify({ passed: checks, network: "none", covers: ["keepalives and split CRLF", "queued status", "private metadata not displayed", "terminal completion", "no ambiguous fallback", "user abort"] }));
} finally { globalThis.fetch = originalFetch; }
