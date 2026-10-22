import assert from "node:assert/strict";
import console from "node:console";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import ts from "typescript";

const require = createRequire(import.meta.url);
function load(relative, imports = {}) {
  const source = fs.readFileSync(path.resolve(import.meta.dirname, relative), "utf8");
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText;
  const module = { exports: {} };
  new Function("exports", "module", "require", output)(module.exports, module, (name) => name.endsWith(".css") ? {} : imports[name] || require(name));
  return module.exports;
}
const contract = load("../components/chat/experience-contract.ts");
const { AnswerMarkdown, answerSourceLinks } = load("../components/chat/answer-markdown.tsx", {
  "react-markdown": { __esModule: true, default: ReactMarkdown }, "./experience-contract": contract,
});
const render = (text, allowedLinks) => renderToStaticMarkup(React.createElement(AnswerMarkdown, { text, allowedLinks }));
const joint = "https://www.wowmd.com/products/joint-support";
const text = `WOWMD offers a variety of wellness products... Some of our popular options include:\n\n* **[Joint Support](${joint}):** Combines ingredients like MSM, plant-based GlucosaGreen® glucosamine, turmeric, Boswellia serrata, white willow bark, hyaluronic acid, and black pepper extract...\n* **[Turmeric Boost](https://www.wowmd.com/products/turmeric-boost):** A plant-based formula...\n* **Collections & Other Essentials:** We also offer targeted ranges for [eye health](https://www.wowmd.com/collections/eye-health-supplements), [digestion](https://www.wowmd.com/collections/digestion-supplements).`;
const html = render(text);
assert.equal((html.match(/<li>/g) || []).length, 3);
assert.match(html, /<strong><a href="https:\/\/www.wowmd.com\/products\/joint-support" target="_blank" rel="noopener noreferrer">Joint Support<\/a>:/);
assert.match(html, /GlucosaGreen®/);
assert(!html.includes("**") && !html.includes("[Joint Support]"));

const unsafe = render('[script](javascript:alert%281%29) [data](data:text/html,test) [credentials](https://user:pass@example.com) [relative](/admin) ![image description](https://bad.invalid/pixel.png)\n\n<script>alert(1)</script>\n\n<img src="https://bad.invalid/raw.png" onerror="alert(1)">');
assert(!/<a |<img|<script|onerror=/.test(unsafe));
assert(unsafe.includes("image description"));

const restricted = render(`[verified](${joint}) [unverified](https://bad.invalid)`, answerSourceLinks([{ source_url: joint }]));
assert.equal((restricted.match(/<a /g) || []).length, 1);
assert(restricted.includes('<span>unverified</span>'));
assert.equal(answerSourceLinks([{ filename: "uploaded.txt" }]), undefined);
assert.match(render(`[ordinary message link](${joint})`, answerSourceLinks([])), /<a /);
assert(!render(`[widget-unverified](${joint})`, new Set()).includes("<a "));

const literals = render('Literal \\*stars\\* and `**code**`\n\n1. First\n2. Second');
assert(literals.includes("Literal *stars*") && literals.includes("<code>**code**</code>"));
assert(literals.includes("<ol>") && !literals.includes("<em>stars</em>"));
console.log(JSON.stringify({ passed: 5, network: "none", checks: ["reported WOWMD Markdown", "unsafe URLs/raw HTML/images", "source restrictions and upload fallback", "widget strict policy", "literal escapes/code/ordered lists"] }));
