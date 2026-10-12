import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium } from "playwright";

// Real DOM/stream consumption; all API responses are deterministic local test
// doubles. No RAG, provider, Railway, or external network request is made.
const widget = await readFile(new URL("../public/widget.js", import.meta.url), "utf8");
const browser = await chromium.launch({ headless: true });
let checks = 0;

async function fixture({ withoutRandomUUID = false } = {}) {
  const context = await browser.newContext();
  if (withoutRandomUUID) await context.addInitScript(() => {
    Object.defineProperty(window.crypto, "randomUUID", { value: undefined });
    const randomValues = window.crypto.getRandomValues.bind(window.crypto);
    window.randomValuesCalls = 0;
    Object.defineProperty(window.crypto, "getRandomValues", { value(values) {
      window.randomValuesCalls += 1;
      return randomValues(values);
    } });
  });
  const sessions = new Map();
  const calls = [];
  let serial = 0;
  let mode = "success";
  const source = { citation_index: 27, title: "Authorized source", doc_id: "doc", chunk_id: "chunk", source_url: "https://verified.example/source" };
  await context.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<script src="/widget.js" data-bot-id="w128" data-api-base-url="http://widget.test"></script>' });
    if (path === "/widget.js") return route.fulfill({ contentType: "application/javascript", body: widget });
    const payload = route.request().postDataJSON() || {};
    calls.push({ path, payload });
    if (path === "/public/widget/w128") return route.fulfill({ json: { native_session_v1: true, bot_name: "Test" } });
    if (path === "/public/widget/w128/session") {
      const id = "session-" + ++serial;
      sessions.set(id, { token: "token-" + serial, turns: [], active: null });
      return route.fulfill({ json: { session_id: id, session_token: "token-" + serial } });
    }
    const session = sessions.get(payload.session_id);
    if (!session || session.token !== payload.session_token) return route.fulfill({ status: 401, body: "denied" });
    if (path.endsWith("/state")) return route.fulfill({ json: { turns: session.turns, active_turn_id: session.active } });
    if (path.endsWith("/ack")) {
      const turn = session.turns.find((t) => t.turn_id === payload.turn_id);
      assert.equal(payload.answer, turn.answer);
      assert.equal(payload.rendered_text, "haha café [ID:27]");
      assert.ok(payload.rendered_at_ms >= payload.first_visible_ms);
      assert.ok(payload.first_visible_ms >= payload.submitted_at_ms && payload.submitted_at_ms > 0);
      turn.delivery = "browser_confirmed";
      return route.fulfill({ status: 204 });
    }
    if (path.endsWith("/abort")) {
      const turn = session.turns.find((t) => t.turn_id === payload.turn_id);
      if (turn) turn.status = "cancelled";
      session.active = null;
      return route.fulfill({ json: { cancelled: true } });
    }
    if (path.endsWith("/source-preview")) {
      assert.fail("The widget must not request source previews");
    }
    if (path.endsWith("/stream")) {
      assert.match(payload.turn_id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
      assert.equal(Object.hasOwn(payload, "history"), false, "Browser must not inject semantic history");
      assert.equal(session.turns.some((t) => t.turn_id === payload.turn_id), false, "No duplicate generation");
      const turn = { turn_id: payload.turn_id, question: payload.message, answer: "", status: "running", citations: [], delivery: "not_confirmed" };
      session.turns.push(turn);
      const event = (data) => "data: " + JSON.stringify({ turn_id: turn.turn_id, ...data }) + "\n\n";
      let body = event({ type: "queued", message: "Queued" });
      body += event({ type: "token", turn_id: "obsolete-turn", token: "WRONG OLD ANSWER" });
      if (mode === "failure") {
        turn.status = "failed";
        body += event({ type: "error", message: "Provider unavailable" });
      } else if (mode === "partial") {
        turn.status = "failed";
        body += event({ type: "token", token: "Partial visible text" });
        // EOF without done: delivery uncertainty, not a generation retry.
      } else if (mode === "queued") {
        session.active = turn.turn_id;
      } else {
        turn.answer = "haha café [ID:27]";
        turn.status = "completed";
        turn.citations = [source];
        body += event({ type: "token", token: "ha" }) + event({ type: "token", token: "ha café [ID:27]" });
        body += event({ type: "sources", sources: [source] });
        body += event({ type: "done", answer: "" });
      }
      return route.fulfill({ contentType: "text/event-stream", body });
    }
    return route.fulfill({ status: 404, body: "missing" });
  });
  const page = await context.newPage();
  await page.goto("http://widget.test");
  await page.locator(".cw-launcher").click();
  await page.locator(".cw-new-chat").waitFor({ state: "visible" });
  await page.waitForFunction(() => [...document.querySelectorAll("div")].some((n) => n.shadowRoot?.querySelector(".cw-input:not(:disabled)")));
  async function ask(text) {
    await page.locator(".cw-input").fill(text);
    await page.locator(".cw-send").click();
    await page.waitForTimeout(120);
  }
  return { context, page, calls, sessions, ask, setMode(value) { mode = value; } };
}

try {
  const f = await fixture();
  f.setMode("failure");
  await f.ask("Old product question");
  await f.page.locator('.cw-message-assistant[data-status="failed"]').waitFor();
  f.setMode("success");
  await f.ask("A different current product question");
  await f.page.locator('.cw-message-assistant[data-status="completed"]').waitFor();
  assert.equal(await f.page.locator(".cw-message-user").count(), 2);
  assert.equal(await f.page.locator('.cw-message-assistant[data-status="completed"] .cw-bubble').innerText(), "haha café [ID:27]");
  assert.equal((await f.page.locator(".cw-messages").innerText()).includes("WRONG OLD ANSWER"), false);
  assert.equal(f.calls.filter((r) => r.path.endsWith("/stream")).length, 2);
  checks += 7;

  const citation = f.page.locator("a.cw-citation");
  assert.equal(await citation.getAttribute("href"), "https://verified.example/source");
  assert.equal(await citation.getAttribute("target"), "_blank");
  assert.equal(await citation.getAttribute("rel"), "noopener noreferrer");
  assert.equal(await f.page.locator("button.cw-citation, .cw-source-preview").count(), 0);
  assert.equal(f.calls.some((r) => r.path.endsWith("/source-preview")), false);
  checks += 5;

  await f.page.reload();
  await f.page.locator(".cw-launcher").click();
  await f.page.locator("a.cw-citation").waitFor();
  assert.equal(await f.page.locator(".cw-message-user").count(), 2);
  assert.equal(f.calls.filter((r) => r.path.endsWith("/stream")).length, 2);
  assert.equal([...f.sessions.values()][0].turns[1].delivery, "browser_confirmed");
  checks += 3;

  f.setMode("partial");
  await f.ask("Partial reply test");
  await f.page.locator('.cw-message-assistant[data-status="failed"]').last().waitFor();
  assert.match(await f.page.locator(".cw-messages").innerText(), /Partial visible text/);
  await f.page.reload();
  await f.page.locator(".cw-launcher").click();
  await f.page.locator('.cw-message-assistant[data-status="failed"]').last().waitFor();
  assert.match(await f.page.locator(".cw-messages").innerText(), /Partial visible text/);
  assert.equal(f.calls.filter((r) => r.path.endsWith("/stream")).length, 3);
  checks += 3;

  f.setMode("queued");
  await f.ask("Cancel queued reply");
  await f.page.locator(".cw-stop").click();
  await f.page.locator('.cw-message-assistant[data-status="cancelled"]').waitFor();
  assert.equal(f.calls.filter((r) => r.path.endsWith("/abort")).length, 1);
  assert.equal(f.calls.filter((r) => r.path.endsWith("/stream")).length, 4);
  checks += 2;

  await f.page.locator(".cw-new-chat").click();
  await f.page.waitForFunction(() => [...document.querySelectorAll("div")].some((n) => n.shadowRoot?.querySelector(".cw-input:not(:disabled)") && n.shadowRoot.querySelectorAll(".cw-message-user").length === 0));
  assert.equal(await f.page.locator(".cw-message-user").count(), 0);
  assert.equal(f.sessions.size, 2);
  assert.equal([...f.sessions.values()][0].turns.length, 4);
  checks += 3;

  const other = await fixture();
  f.setMode("success"); other.setMode("success");
  await Promise.all([f.ask("Visitor one"), other.ask("Visitor two")]);
  assert.equal([...f.sessions.values()][1].turns[0].question, "Visitor one");
  assert.equal([...other.sessions.values()][0].turns[0].question, "Visitor two");
  assert.equal((await f.page.locator(".cw-messages").innerText()).includes("Visitor two"), false);
  checks += 3;
  await f.context.close(); await other.context.close();

  const fallback = await fixture({ withoutRandomUUID: true });
  await fallback.ask("Fallback UUID first question");
  await fallback.page.locator('.cw-message-assistant[data-status="completed"]').waitFor();
  await fallback.ask("Fallback UUID second question");
  await fallback.page.locator('.cw-message-assistant[data-status="completed"]').nth(1).waitFor();
  const fallbackIds = fallback.calls.filter((r) => r.path.endsWith("/stream")).map((r) => r.payload.turn_id);
  assert.equal(fallbackIds.length, 2);
  assert.notEqual(fallbackIds[0], fallbackIds[1]);
  assert.equal(await fallback.page.evaluate(() => window.crypto.randomUUID), undefined);
  assert.equal(await fallback.page.evaluate(() => window.randomValuesCalls), 2);
  checks += 4;
  await fallback.context.close();

  // Existing non-native product endpoints keep their previous request contract.
  const legacy = await browser.newContext();
  let legacyBody;
  let legacyStreamCalls = 0;
  const legacySource = { title: "Verified product", source_url: "https://verified.example/product" };
  const legacyAnswer = "- **[Verified product](" + legacySource.source_url + "):** Legacy reply.\n" +
    "- **[Unverified](https://unverified.example/product)**";
  await legacy.route("**/*", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<script src="/widget.js" data-bot-id="normal" data-api-base-url="http://legacy.test"></script>' });
    if (path === "/widget.js") return route.fulfill({ contentType: "application/javascript", body: widget });
    if (path === "/public/widget/normal") return route.fulfill({ json: { bot_name: "Legacy" } });
    if (path === "/public/widget/normal/experience" || path.startsWith("/embed/chat/")) return route.fulfill({ status: 404, body: "Optional enhanced view unavailable" });
    if (path.endsWith("/session")) return route.fulfill({ json: { session_id: "legacy", session_token: "local" } });
    if (path.endsWith("/stream")) {
      legacyStreamCalls += 1;
      legacyBody = route.request().postDataJSON();
      const events = [
        { type: "token", token: legacyAnswer },
        { type: "sources", sources: [legacySource] },
        { type: "done" },
      ];
      return route.fulfill({ contentType: "text/event-stream", body: events.map((event) => "data: " + JSON.stringify(event) + "\n\n").join("") });
    }
    throw new Error("Unexpected legacy endpoint " + path);
  });
  const legacyPage = await legacy.newPage();
  await legacyPage.goto("http://legacy.test");
  await legacyPage.locator(".cw-launcher").click();
  await legacyPage.locator(".cw-input").fill("Legacy **question**");
  await legacyPage.locator(".cw-send").click();
  await legacyPage.locator(".cw-bubble strong a").waitFor();
  assert.equal(await legacyPage.locator(".cw-new-chat").isVisible(), false);
  assert.equal(await legacyPage.locator(".cw-stop").isVisible(), false);
  assert.deepEqual(legacyBody.history, []);
  assert.equal(legacyBody.message, "Legacy **question**");
  checks += 4;

  for (const restored of [false, true]) {
    if (restored) {
      await legacyPage.reload();
      await legacyPage.locator(".cw-launcher").click();
      await legacyPage.locator(".cw-bubble strong a").waitFor();
    }
    assert.equal(await legacyPage.locator(".cw-message-assistant .cw-bubble li").count(), 2);
    assert.equal(await legacyPage.locator(".cw-bubble strong a").getAttribute("href"), legacySource.source_url);
    assert.equal(await legacyPage.locator(".cw-sources a").getAttribute("href"), legacySource.source_url);
    assert.equal(await legacyPage.locator('.cw-bubble a[href="https://unverified.example/product"]').count(), 0);
    assert.equal(await legacyPage.locator(".cw-message-user .cw-bubble").innerText(), "Legacy **question**");
    assert.equal(await legacyPage.locator(".cw-message-user strong").count(), 0);
    assert.equal(legacyStreamCalls, 1, "Restoring a reply must not trigger another generation");
    checks += 7;
  }

  await legacyPage.evaluate(() => {
    const key = "chatbot-widget-history-normal-legacy";
    const saved = JSON.parse(sessionStorage.getItem(key));
    for (const message of saved) delete message.sources;
    sessionStorage.setItem(key, JSON.stringify(saved));
  });
  await legacyPage.reload();
  await legacyPage.locator(".cw-launcher").click();
  await legacyPage.locator(".cw-message-assistant .cw-bubble li").first().waitFor();
  assert.equal(await legacyPage.locator(".cw-message-assistant .cw-bubble li").count(), 2);
  assert.equal(await legacyPage.locator(".cw-message-assistant .cw-bubble strong").count(), 2);
  assert.match(await legacyPage.locator(".cw-message-assistant .cw-bubble").innerText(), /Verified product: Legacy reply/);
  assert.equal(await legacyPage.locator(".cw-bubble a, .cw-sources a").count(), 0, "Old records cannot obtain verified links from answer text");
  assert.equal(legacyStreamCalls, 1);
  checks += 5;
  await legacy.close();
  console.log(`Native widget browser checks: ${checks} PASS (no live calls)`);
} finally { await browser.close(); }
