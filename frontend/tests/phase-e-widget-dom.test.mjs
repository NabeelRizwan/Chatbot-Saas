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

// The actual widget normalizer must preserve per-bot copy, not inject a domain.
for (const welcome of ["Welcome to A!", "Hello from B!"]) {
  assert.equal(hooks.normalizeConfig({ welcome_message: welcome }).welcomeMessage, welcome);
}
assert.equal(hooks.normalizeConfig({ welcomeMessage: "Legacy welcome" }).welcomeMessage, "Legacy welcome");
for (const value of [undefined, null, "", "   "]) {
  assert.equal(hooks.normalizeConfig({ welcome_message: value }).welcomeMessage, "Hi, how can I help you today?");
}

function descendants(node) {
  return node.children.flatMap((child) => [child, ...descendants(child)]);
}

{
  const sourceUrl = "https://verified.example/products/chocolate-collagen";
  const answer = "- **[Chocolate Collagen Peptides Powder](" + sourceUrl + "):** Mix one scoop daily.";
  const container = new FakeNode("div");
  hooks.renderSafeMarkdown(container, answer, new Set());
  assert.equal(descendants(container).some((node) => node.tagName === "A"), false);
  assert.equal(container.textContent, "Chocolate Collagen Peptides Powder: Mix one scoop daily.");

  hooks.renderSafeMarkdown(container, answer, hooks.verifiedUrlSet([{ source_url: sourceUrl }]));
  const nodes = descendants(container);
  const link = nodes.find((node) => node.tagName === "A");
  assert.ok(link, "A verified product link inside bold list text must be clickable");
  assert.equal(link.parentNode.tagName, "STRONG");
  assert.equal(link.parentNode.parentNode.tagName, "LI");
  assert.equal(link.textContent, "Chocolate Collagen Peptides Powder");
  assert.equal(link.href, sourceUrl);
  assert.equal(link.target, "_blank");
  assert.equal(link.rel, "noopener noreferrer");
  assert.equal(container.textContent, "Chocolate Collagen Peptides Powder: Mix one scoop daily.");
}

{
  const container = new FakeNode("div");
  const verifiedUrl = "https://verified.example/product";
  hooks.renderSafeMarkdown(
    container,
    "**[Unverified](https://other.example/product)** " +
      "**[Script](javascript:alert%281%29)** " +
      "**[Data](data:text/html,test)** " +
      "**[Credentials](https://user:password@verified.example/product)** " +
      "**[<img src=x onerror=alert(1)>](" + verifiedUrl + ")**",
    new Set([verifiedUrl, "javascript:alert%281%29", "data:text/html,test", "https://user:password@verified.example/product"])
  );
  const nodes = descendants(container);
  const links = nodes.filter((node) => node.tagName === "A");
  assert.equal(links.length, 1, "Bold formatting must not bypass URL validation or source verification");
  assert.equal(links[0].href, verifiedUrl);
  assert.equal(links[0].textContent, "<img src=x onerror=alert(1)>");
  assert.equal(nodes.some((node) => node.tagName === "IMG" || node.tagName === "SCRIPT"), false);
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
