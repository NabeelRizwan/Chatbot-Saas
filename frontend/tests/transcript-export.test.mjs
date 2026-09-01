import assert from "node:assert/strict";

import {
  buildPrintableTranscriptHtml,
  escapeTranscriptHtml,
} from "../lib/transcript-export.ts";

const cases = [
  ["<script>alert(1)</script>", "&lt;script&gt;alert(1)&lt;/script&gt;"],
  ["<img src=x onerror=alert(1)>", "&lt;img src=x onerror=alert(1)&gt;"],
  ["</style><script>alert('x')</script>", "&lt;/style&gt;&lt;script&gt;alert(&#39;x&#39;)&lt;/script&gt;"],
  ["&lt;already encoded&gt;", "&amp;lt;already encoded&amp;gt;"],
  ['Quotes: "double" and \'single\'', "Quotes: &quot;double&quot; and &#39;single&#39;"],
  ["R&D & Support", "R&amp;D &amp; Support"],
  ["**ordinary Markdown** [link](https://example.com)", "**ordinary Markdown** [link](https://example.com)"],
  ["line one\nline two", "line one\nline two"],
];

for (const [input, expected] of cases) {
  assert.equal(escapeTranscriptHtml(input), expected);
}

const html = buildPrintableTranscriptHtml({
  title: "<script>title()</script>",
  botName: '<img src=x onerror="bot()">',
  sessionId: 'session-"<&',
  createdAt: "2026-08-20 & later",
  messages: cases.map(([input]) => ({
    userMessage: input,
    assistantResponse: input,
    createdAt: "10:30 <AM>",
  })),
});

assert.doesNotMatch(html, /<script[\s>]/i);
assert.doesNotMatch(html, /<img[\s>]/i);
assert.doesNotMatch(html, /<\/style>\s*<script/i);
assert.match(html, /&lt;script&gt;title\(\)&lt;\/script&gt;/);
assert.match(html, /&lt;img src=x onerror=&quot;bot\(\)&quot;&gt;/);
assert.match(html, /line one\nline two/);
assert.match(html, /\*\*ordinary Markdown\*\*/);
assert.match(html, /class="timestamp">10:30 &lt;AM&gt;/);
