import assert from "node:assert/strict";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright";

// Runs the real assistant-ui Next view and legacy host transport against a
// deterministic session server. No provider calls or production writes occur.
const base = process.env.E2E_BASE_URL || "http://localhost:3310";
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext();
const calls = [];
let turns = [];
let sessionCount = 0;
let pendingProducts = true;
let mode = "success";
const source = { title: "Verified product", source_url: "https://shop.example/product", citation_index: 7 };
const settings = { enabled: true, hosted_chat_enabled: true, lead_form_enabled: true, product_cards_enabled: true, lead_consent_text: "I agree to be contacted.", suggested_questions: ["What is the daily amount?"], theme: "dark", font_family: "system", density: "compact", corner_style: "soft" };
await context.route("**/public/**", async (route) => {
  const path = new URL(route.request().url()).pathname;
  const payload = route.request().postDataJSON();
  calls.push({ path, payload });
  if (path.endsWith("/experience")) return route.fulfill({ json: settings });
  if (path.endsWith("/experience/integrations")) return route.fulfill({ json: { booking: { enabled: true, label: "Book an appointment", url: "https://cal.com/example" }, orders: { enabled: false } } });
  if (path.endsWith("/experience/leads")) { assert.equal(payload.session_token, "private-session"); assert.equal(payload.consent, true); return route.fulfill({ json: { received: true } }); }
  if (path.endsWith("/experience/products/for-turn")) {
    if (pendingProducts) { pendingProducts = false; return route.fulfill({ json: { products: [], pending: true } }); }
    return route.fulfill({ json: { products: [{ id: "p1", title: "Verified product", url: source.source_url, description: "Daily care.", price_amount: "15.00", currency: "USD" }], pending: false } });
  }
  if (path.endsWith("/session")) { sessionCount++; turns = []; return route.fulfill({ json: { session_id: "session-" + sessionCount, session_token: "private-session" } }); }
  if (path.endsWith("/state")) return route.fulfill({ json: { turns, active_turn_id: mode === "queued" ? turns.at(-1)?.turn_id : null } });
  if (path.endsWith("/ack")) {
    assert.equal(payload.answer, "Take **two** daily. [ID:7]\n\n[Unsafe](https://unverified.example)");
    assert.match(payload.rendered_text, /Take two daily/);
    assert.doesNotMatch(payload.rendered_text, /ID:7/, "Ack must contain the React citation rendering, not the hidden fallback DOM");
    assert.ok(payload.first_visible_ms >= payload.submitted_at_ms);
    const turn = turns.find((item) => item.turn_id === payload.turn_id); turn.delivery = "browser_confirmed";
    return route.fulfill({ status: 204 });
  }
  if (path.endsWith("/abort")) { turns.at(-1).status = "cancelled"; mode = "success"; return route.fulfill({ json: { cancelled: true } }); }
  if (path.endsWith("/stream")) {
    assert.equal(Object.hasOwn(payload, "history"), false);
    assert.equal(payload.session_token, "private-session");
    const turn = { turn_id: payload.turn_id, question: payload.message, answer: "", citations: [], status: "queued", delivery: "not_confirmed", created_at: new Date().toISOString() };
    turns.push(turn);
    const event = (value) => `data: ${JSON.stringify({ turn_id: turn.turn_id, ...value })}\n\n`;
    if (mode === "queued") return route.fulfill({ contentType: "text/event-stream", body: event({ type: "meta", queued: true, buffered: true }) + ": keepalive\n\n" });
    turn.answer = "Take **two** daily. [ID:7]\n\n[Unsafe](https://unverified.example)"; turn.citations = [source]; turn.status = "completed";
    return route.fulfill({ contentType: "text/event-stream", body: event({ type: "token", token: turn.answer }) + event({ type: "sources", sources: [source] }) + event({ type: "done" }) });
  }
  return route.fulfill({ json: { bot_name: "Test assistant", native_session_v1: true, welcome_message: "How can I help?", primary_color: "#397255", placeholder_text: "Ask us anything" } });
});

try {
  const page = await context.newPage();
  const failures = [];
  page.on("pageerror", (error) => failures.push(error.message));
  await page.goto(`${base}/chat/ui-test`);
  const frame = page.frameLocator("iframe.cw-react-frame");
  await frame.locator(".aui-shell").waitFor({ timeout: 90_000 });
  await frame.getByRole("button", { name: "What is the daily amount?" }).click();
  await frame.locator(".aui-product").waitFor();
  await page.waitForTimeout(250);
  assert.equal(calls.filter((item) => item.path.endsWith("/stream")).length, 1);
  assert.ok(calls.some((item) => item.path.endsWith("/ack")), "Acknowledgment must follow actual React rendering");
  assert.ok(await frame.locator(".aui-shell").evaluate((element) => element.classList.contains("aui-theme-dark")));
  assert.equal(await frame.locator('a[href="https://unverified.example"]').count(), 0);
  assert.equal(await frame.locator('a[href="https://shop.example/product"]').count(), 3);
  assert.equal(await frame.getByText("Track an order").count(), 0, "Unconfigured integrations stay hidden");
  assert.equal(await frame.getByRole("link", { name: "Book an appointment" }).getAttribute("href"), "https://cal.com/example");
  assert.equal(await frame.getByRole("link", { name: "Book an appointment" }).getAttribute("rel"), "noopener noreferrer");
  await frame.getByRole("button", { name: "Contact us" }).click();
  await frame.getByLabel("Name", { exact: true }).fill("Visitor One");
  await frame.getByLabel("Email", { exact: true }).fill("visitor@example.test");
  await frame.getByLabel("I agree to be contacted.").check();
  await frame.getByRole("button", { name: "Send details" }).click();
  await frame.getByText("Thanks. Your details have been received.").waitFor();
  assert.equal(calls.filter((item) => item.path.endsWith("/experience/leads")).length, 1);
  await frame.getByRole("button", { name: "Close contact form" }).click();
  const streamCount = calls.filter((item) => item.path.endsWith("/stream")).length;
  await page.evaluate(() => {
    const host = Array.from(document.querySelectorAll("div")).find((element) => element.shadowRoot?.querySelector("iframe.cw-react-frame"));
    const iframe = host.shadowRoot.querySelector("iframe.cw-react-frame");
    const nonce = new URLSearchParams(new URL(iframe.src).hash.slice(1)).get("nonce");
    window.postMessage({ channel: "chatbot-assistant-ui-v1", nonce, action: "send", text: "FORGED" }, window.location.origin);
  });
  await page.waitForTimeout(100);
  assert.equal(calls.filter((item) => item.path.endsWith("/stream")).length, streamCount, "Untrusted bridge messages cannot send chat requests");
  await frame.getByRole("button", { name: "Start a new chat" }).click();
  await frame.getByRole("button", { name: "What is the daily amount?" }).waitFor();
  assert.equal(sessionCount, 2);
  mode = "queued";
  await frame.getByRole("textbox", { name: "Your message" }).fill("Cancel this queued question");
  await frame.getByRole("button", { name: "Send message" }).click();
  await frame.getByRole("status").filter({ hasText: "Waiting for the knowledge pipeline" }).waitFor();
  await frame.getByRole("button", { name: "Stop reply" }).click();
  await frame.getByText("Reply stopped.").waitFor();
  assert.equal(calls.filter((item) => item.path.endsWith("/abort")).length, 1);
  assert.deepEqual(failures, []);
  await page.screenshot({ path: process.env.WIDGET_SCREENSHOT || join(tmpdir(), "chatbot-assistant-ui-widget.png"), fullPage: true });
  const legacy = await browser.newContext();
  const legacyCalls = [];
  let failLegacy = true;
  await legacy.route("**/public/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/experience")) return route.fulfill({ json: { ...settings, product_cards_enabled: false, lead_form_enabled: false } });
    if (path.endsWith("/experience/integrations")) return route.fulfill({ json: {} });
    if (path.endsWith("/session")) return route.fulfill({ json: { session_id: "legacy-session", session_token: "legacy-token" } });
    if (path.endsWith("/stream")) {
      const payload = route.request().postDataJSON(); legacyCalls.push(payload);
      const events = failLegacy ? [{ type: "error", message: "Temporary failure" }] : [{ type: "token", token: "A **complete** answer." }, { type: "sources", sources: [source] }, { type: "done" }];
      return route.fulfill({ contentType: "text/event-stream", body: events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("") });
    }
    return route.fulfill({ json: { bot_name: "Existing pipeline", native_session_v1: false } });
  });
  const legacyPage = await legacy.newPage();
  await legacyPage.goto(`${base}/chat/legacy-test`);
  const legacyFrame = legacyPage.frameLocator("iframe.cw-react-frame");
  await legacyFrame.getByRole("button", { name: "What is the daily amount?" }).click();
  await legacyFrame.getByRole("button", { name: "Retry", exact: true }).waitFor();
  failLegacy = false;
  await legacyFrame.getByRole("button", { name: "Retry", exact: true }).click();
  await legacyFrame.getByText("A complete answer.").waitFor();
  assert.equal(legacyCalls.length, 2);
  assert.equal(legacyCalls[0].turn_id, legacyCalls[1].turn_id, "Retry must reuse the original delivery ID");
  assert.equal(legacyCalls[1].retry, true);
  assert.deepEqual(legacyCalls[1].history, []);
  assert.equal(await legacyFrame.locator(".aui-user").count(), 1);
  await legacyPage.reload();
  await legacyFrame.getByText("A complete answer.").waitFor();
  assert.equal(legacyCalls.length, 2, "Reload must restore delivery without generating again");
  assert.equal(await legacyFrame.locator(".aui-user").count(), 1);
  await legacy.close();
  const disabled = await browser.newContext();
  let disabledSessionCalls = 0;
  await disabled.route("**/public/**", async (route) => {
    if (new URL(route.request().url()).pathname.endsWith("/session")) disabledSessionCalls++;
    return route.fulfill({ json: { enabled: true, hosted_chat_enabled: false } });
  });
  const disabledPage = await disabled.newPage();
  await disabledPage.goto(`${base}/chat/disabled-test`);
  await disabledPage.getByText("This chatbot link has not been enabled.").waitFor();
  assert.equal(await disabledPage.locator("iframe.cw-react-frame").count(), 0);
  assert.equal(disabledSessionCalls, 0, "Disabled hosted links must not issue a visitor session");
  await disabled.close();
  console.log("assistant-ui: real rendering, strict bridge, native delivery ack, source safety, lead persistence, verified products, appearance, optional actions, reset and cancellation PASS");
  console.log("assistant-ui: existing pipeline retry/idempotency and reload recovery PASS");
  console.log("assistant-ui: disabled hosted link fails closed without issuing session; configured links are exact HTTPS noopener links PASS");
} finally { await browser.close(); }
