import assert from "node:assert/strict";

class FakeNode {
  constructor(tagName, text) {
    this.tagName = tagName ? tagName.toUpperCase() : null;
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this._text = text || "";
  }
  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  set textContent(value) {
    this.children = [];
    this._text = String(value || "");
  }
  get textContent() {
    return this._text + this.children.map((child) => child.textContent).join("");
  }
  set href(value) { this.attributes.href = value; }
  get href() { return this.attributes.href; }
  set target(value) { this.attributes.target = value; }
  get target() { return this.attributes.target; }
  set rel(value) { this.attributes.rel = value; }
  get rel() { return this.attributes.rel; }
}

globalThis.document = {
  currentScript: null,
  createElement(tag) { return new FakeNode(tag); },
  createTextNode(text) { return new FakeNode(null, String(text)); },
};
globalThis.window = {
  __CHATBOT_WIDGET_ENABLE_TEST_HOOKS__: true,
  ChatbotWidget: null,
};

await import("../public/widget.js");
const hooks = globalThis.window.ChatbotWidget.__test;

function descendants(node) {
  return node.children.flatMap((child) => [child, ...descendants(child)]);
}

{
  const container = new FakeNode("div");
  hooks.renderSafeMarkdown(
    container,
    "<script>globalThis.pwned=true</script>\n\n[Bad](javascript:alert(1))",
    new Set()
  );
  assert.equal(descendants(container).some((node) => node.tagName === "SCRIPT"), false);
  assert.equal(descendants(container).some((node) => node.tagName === "A"), false);
  assert.match(container.textContent, /<script>/);
}

{
  const sourceUrl = "https://verified.example/product";
  const verified = hooks.verifiedUrlSet([
    { source_url: sourceUrl, cta_links: [{ label: "Buy", url: "https://verified.example/buy" }] },
  ]);
  const container = new FakeNode("div");
  hooks.renderSafeMarkdown(
    container,
    "**Details**\n\n- First\n- Second\n\n[Product](" + sourceUrl + ")",
    verified
  );
  const nodes = descendants(container);
  assert.equal(nodes.some((node) => node.tagName === "STRONG"), true);
  assert.equal(nodes.some((node) => node.tagName === "UL"), true);
  const link = nodes.find((node) => node.tagName === "A");
  assert.equal(link.href, sourceUrl);
  assert.equal(link.target, "_blank");
  assert.equal(link.rel, "noopener noreferrer");
}

{
  const container = new FakeNode("div");
  hooks.renderSafeMarkdown(
    container,
    "| Plan | Price |\n| --- | --- |\n| Basic | $10 |\n| Pro | $20 |",
    new Set()
  );
  assert.equal(descendants(container).some((node) => node.tagName === "TABLE"), true);
  assert.match(container.textContent, /Basic/);
  assert.match(container.textContent, /\$20/);
}

assert.equal(hooks.safeHttpUrl("javascript:alert(1)"), null);
assert.equal(hooks.safeHttpUrl("data:text/html,<script>1</script>"), null);
