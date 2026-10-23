import assert from "node:assert/strict";
import console from "node:console";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import ts from "typescript";

// Independent contracts, not benchmark questions: no servers or model calls.
const require = createRequire(import.meta.url);
function load(relative, imports = {}) {
  const source = fs.readFileSync(path.resolve(import.meta.dirname, relative), "utf8");
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText;
  const module = { exports: {} };
  new Function("exports", "module", "require", output)(module.exports, module, name => name.endsWith(".css") ? {} : imports[name] || require(name));
  return module.exports;
}
const contract = load("../components/chat/experience-contract.ts");
const { SourceLinks } = load("../components/chat/source-links.tsx", { "./experience-contract": contract });
const { AnswerMarkdown, answerSourceLinks } = load("../components/chat/answer-markdown.tsx", { "./experience-contract": contract, "react-markdown": { __esModule: true, default: ReactMarkdown } });
globalThis.document = { currentScript: null };
globalThis.window = { __CHATBOT_WIDGET_ENABLE_TEST_HOOKS__: true };
await import("../public/widget.js");
const widget = globalThis.window.ChatbotWidget.__test;
let checks = 0;
const fixtures = [
  { title: "Train timetable", source_url: "https://rail.example/schedules?route=A%20B#weekdays" },
  { title: "Board specifications", source_url: "https://hardware.example/models/board-4" },
  { title: "Rental terms", source_url: "https://hire.example/terms/v2" },
  { title: "取扱説明書", source_url: "https://docs.example/%E8%AA%AC%E6%98%8E.pdf#page=8" },
  { title: "Library hours", source_url: "http://library.example/hours" },
  { title: "Museum visiting", cta_links: [{ label: "Accessibility", url: "https://museum.example/access" }] },
  { filename: "Private workshop notes.pdf", source_url: "document://482" },
];
for (const sources of [fixtures, [fixtures[0], fixtures[0]], [], [{ filename: "notes.txt" }]]) {
  assert.deepEqual(widget.sourceLinks(sources), contract.sourceLinks(sources));
  assert.deepEqual([...widget.verifiedUrlSet(sources)].sort(), [...contract.verifiedLinks(sources)].sort());
  checks++;
}
const rendered = renderToStaticMarkup(React.createElement(SourceLinks, { sources: [...fixtures, fixtures[0]] }));
assert.equal((rendered.match(/<a /g) || []).length, 6);
assert.equal((rendered.match(/rel="noopener noreferrer"/g) || []).length, 6);
assert.equal((rendered.match(/Train timetable/g) || []).length, 1);
assert.match(rendered, /<span[^>]*>Private workshop notes.pdf<\/span>/);
assert(!rendered.includes("document://"));
checks++;
for (const bad of ["javascript:alert(1)", "data:text/plain,test", "file:///secret", "/admin", "https:example.test", "https:/example.test", "https:///example.test", "https://user:pass@example.test", "https://@example.test", "https://example.test/a\nb", "https://example.test/a\tb", "https://example.test/a\u0085b", "https://example.test/a\u00a0b", "https:\\example.test\\path", "https://example.test/a b", "https://example.test/" + "x".repeat(2048)]) {
  assert.equal(contract.safeLink(bad), null); assert.equal(widget.safeHttpUrl(bad), null);
  const source = { title: "<script>bad()</script>", source_url: bad };
  const html = renderToStaticMarkup(React.createElement(SourceLinks, { sources: [source] }));
  assert(!html.includes("<a ") && !html.includes("<script>"));
  checks++;
}
const answer = "The workshop starts at **09:30**. [Schedule](https://rail.example/schedules?route=A%20B#weekdays) [Unverified](https://unrelated.example/guess)";
const html = renderToStaticMarkup(React.createElement(AnswerMarkdown, { text: answer, allowedLinks: answerSourceLinks([fixtures[0]]) }));
assert.equal((html.match(/<a /g) || []).length, 1);
assert.match(html, /<span>Unverified<\/span>/);
assert.match(html, /<strong>09:30<\/strong>/);
assert(!renderToStaticMarkup(React.createElement(AnswerMarkdown, { text: answer, allowedLinks: answerSourceLinks([]) })).includes("<a "));
checks++;
const candidates = [{ ...fixtures[0], citation_index: 2 }, { ...fixtures[1], citation_index: 7 }];
const selected = { ...fixtures[2], attribution_scope: "selected" };
assert.deepEqual(widget.presentedSources("Unmarked prose", candidates, true), []);
assert.deepEqual(widget.presentedSources("A fact. [ID:7]", [...candidates, selected], true), [candidates[1], selected]);
assert.deepEqual(widget.presentedSources("Unmarked prose", [selected], true), [selected]);
assert.deepEqual(widget.presentedSources("Unmarked prose", candidates, false), candidates);
assert.deepEqual(widget.presentedSources("Unmarked prose", JSON.parse(JSON.stringify([selected])), true), [selected]);
checks++;
const malformedSources = [null, false, "not metadata", { title: {}, cta_links: "not an array" }, { title: "Reader", cta_links: [null, false, { url: "https://reader.example/guide", label: {} }] }];
assert.deepEqual(contract.sourceLinks(malformedSources), widget.sourceLinks(malformedSources));
assert.doesNotThrow(() => renderToStaticMarkup(React.createElement(SourceLinks, { sources: malformedSources })));
checks++;
for (const sources of [
  [{ citation_index: 1, ...fixtures[0] }, { citation_index: 1, ...fixtures[1] }],
  [{ citation_index: 1, ...fixtures[0] }, { citation_index: 1, filename: "Unknown" }],
]) {
  assert.equal(contract.citationUrlMap(sources).size, 0);
  assert.equal(widget.citationUrlMap(sources).size, 0);
  assert.deepEqual(widget.presentedSources("A fact. [ID:1]", sources, true), []);
  assert.deepEqual(widget.sourceLinks(widget.presentedSources("A fact. [ID:1]", sources, true)), []);
  assert.equal(contract.displayAnswer({ content: "A fact. [ID:1]", sources }), "A fact. [ID:1]");
  checks++;
}
const duplicate = [{ citation_index: 1, ...fixtures[0] }, { citation_index: 1, ...fixtures[0] }];
assert.deepEqual([...contract.citationUrlMap(duplicate)], [...widget.citationUrlMap(duplicate)]);
assert.equal(contract.citationUrlMap(duplicate).size, 1);
assert.equal(widget.sourceLinks(widget.presentedSources("A fact. [ID:1]", duplicate, true)).length, 1);
assert.deepEqual(widget.presentedSources("A fact. [ID:1]", [{ ...fixtures[1], attribution_scope: "selected", citation_index: 1 }, ...duplicate], true), [{ ...fixtures[1], attribution_scope: "selected", citation_index: 1 }]);
checks++;
const many = Array.from({ length: 15 }, (_, index) => ({ title: "Independent manual " + index, source_url: `https://manuals.example/${index}` }));
assert.equal(widget.sourceLinks(many).length, 15);
assert.equal(contract.sourceLinks(many).length, 15);
checks++;
console.log(JSON.stringify({ passed: checks, network: "none", domains: ["travel", "hardware", "rental", "multilingual manual", "library", "museum", "private upload"], contract: "same selected sidecar links, strict URL allowlists, native legacy semantics retained" }));
