import { expect, test, type Page } from "@playwright/test";

// Rendered playground with synthetic auth/data and intercepted chat. No backend
// or provider request may escape this fixture.
async function mockPlayground(page: Page, streamBody = "", streamStatus = 200) {
  const calls: string[] = [];
  await page.addInitScript(() => localStorage.setItem("chatbot-saas-auth", JSON.stringify({ state: { selectedOrganizationId: "9", activeOrganizationRole: "owner", user: { id: "1", name: "Owner", email: "owner@example.test", is_admin: false } }, version: 0 })));
  await page.route("**/*", async (route) => {
    const req = route.request(); const url = new URL(req.url()); const path = url.pathname;
    if (!["fetch", "xhr"].includes(req.resourceType()) || path.startsWith("/_next") || url.searchParams.has("_rsc")) return route.continue();
    calls.push(path);
    if (path === "/auth/refresh") return route.fulfill({ json: { access_token: "synthetic", user: { id: 1, name: "Owner", email: "owner@example.test", is_admin: false } } });
    if (path === "/organizations/") return route.fulfill({ json: [{ id: 9, name: "Example", role: "owner", slug: "example", created_at: "2026-10-12" }] });
    if (path === "/bot/7") return route.fulfill({ json: { id: 7, organization_id: 9, name: "Synthetic bot", provider: "gemini", model_name: "models/gemini-3.5-flash-lite", status: "active" } });
    if (path === "/knowledge/documents") return route.fulfill({ json: { documents: [] } });
    if (path === "/knowledge/jobs") return route.fulfill({ json: { jobs: [] } });
    if (path.endsWith("/usage")) return route.fulfill({ json: { organization_id: 9, current_plan: "free", usage: {}, limits: {}, current_period: { start: "2026-10-01", end: null }, metering: {} } });
    if (path === "/chat/7/stream") return route.fulfill({ status: streamStatus, contentType: "text/event-stream", body: streamBody });
    if (path === "/chat/7") return route.fulfill({ json: { reply: "Compatibility answer.", answer: "Compatibility answer.", sources: [], retrieved_chunks: [] } });
    return route.fulfill({ status: 503, json: { detail: "Unexpected isolated test request: " + path } });
  });
  return calls;
}
async function ask(page: Page, question = "Synthetic question") {
  await page.goto("/knowledge/7");
  await expect(page.getByRole("heading", { name: "Synthetic bot", exact: true })).toBeVisible();
  await page.getByPlaceholder("Ask about uploaded docs or crawled pages...").fill(question);
  await page.getByRole("button", { name: "Send playground message", exact: true }).click();
}

for (const [name, body] of [
  ["server error", 'data: {"type":"meta","queued":true}\n\nevent: error\ndata: {"detail":"Synthetic failure"}\n\n'],
  ["truncated answer", 'data: {"token":"Incomplete answer."}\n\n'],
] as const) {
  test(`accepted ${name} is not automatically sent again`, async ({ page }) => {
    const calls = await mockPlayground(page, body);
    await ask(page);
    await expect(page.getByText("The reply could not be completed. The question was not sent again. Check conversation history before sending it again.", { exact: true })).toBeVisible();
    expect(calls.filter((path) => path === "/chat/7/stream")).toHaveLength(1);
    expect(calls.filter((path) => path === "/chat/7")).toHaveLength(0);
  });
}

test("explicitly unsupported stream route retains compatibility fallback", async ({ page }) => {
  const calls = await mockPlayground(page, "", 404);
  await ask(page);
  await expect(page.getByText("Compatibility answer.", { exact: true })).toBeVisible();
  expect(calls.filter((path) => path === "/chat/7/stream")).toHaveLength(1);
  expect(calls.filter((path) => path === "/chat/7")).toHaveLength(1);
});

async function bufferedStream(page: Page) {
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window);
    const state = { calls: 0, aborted: false, keepalive: () => {}, finish: () => {} };
    (window as unknown as { syntheticStream: typeof state }).syntheticStream = state;
    window.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (url.pathname !== "/chat/7/stream") return originalFetch(input, init);
      state.calls++;
      return new Response(new ReadableStream({ start(controller) {
        const encoder = new TextEncoder();
        const emit = (value: unknown) => controller.enqueue(encoder.encode(`data: ${JSON.stringify(value)}\n\n`));
        init?.signal?.addEventListener("abort", () => { state.aborted = true; controller.error(new DOMException("Stopped", "AbortError")); }, { once: true });
        emit({ type: "meta", queued: true, buffered: true });
        emit({ source_map: "private_map_must_not_display" });
        state.keepalive = () => controller.enqueue(encoder.encode(": keepalive\n\n"));
        state.finish = () => { emit({ token: "Approved final answer." }); emit({ done: true }); controller.close(); };
      } }), { headers: { "Content-Type": "text/event-stream" } });
    };
  });
}

test("buffered stream remains pending across a simulated 35-minute wait and displays only final text", async ({ page }) => {
  await mockPlayground(page);
  await bufferedStream(page);
  await page.clock.install();
  await ask(page);
  await expect(page.getByRole("status").filter({ hasText: "Waiting for the knowledge pipeline" })).toBeVisible();
  await page.evaluate(() => (window as unknown as { syntheticStream: { keepalive: () => void } }).syntheticStream.keepalive());
  await page.clock.fastForward(35 * 60 * 1000);
  await expect(page.getByRole("button", { name: "Stop playground reply", exact: true })).toBeVisible();
  await expect(page.locator("body")).not.toContainText("private_map_must_not_display");
  await page.evaluate(() => (window as unknown as { syntheticStream: { finish: () => void } }).syntheticStream.finish());
  await expect(page.getByText("Approved final answer.", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { syntheticStream: { calls: number } }).syntheticStream.calls)).toBe(1);
});

test("stop aborts a pending playground stream and does not resend", async ({ page }) => {
  const calls = await mockPlayground(page);
  await bufferedStream(page);
  await ask(page);
  await expect(page.getByRole("status").filter({ hasText: "Waiting for the knowledge pipeline" })).toBeVisible();
  await page.getByRole("button", { name: "Stop playground reply", exact: true }).click();
  await expect(page.getByText("Reply stopped.", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { syntheticStream: { aborted: boolean } }).syntheticStream.aborted)).toBe(true);
  expect(calls.filter((path) => path === "/chat/7")).toHaveLength(0);
});

const productAnswer = "WOWMD offers a variety of wellness products... Some of our popular options include:\n\n* **[Joint Support](https://www.wowmd.com/products/joint-support):** Combines ingredients like MSM, plant-based GlucosaGreen® glucosamine, turmeric, Boswellia serrata, white willow bark, hyaluronic acid, and black pepper extract...\n* **[Turmeric Boost](https://www.wowmd.com/products/turmeric-boost):** A plant-based formula...\n* **Collections & Other Essentials:** We also offer targeted ranges for [eye health](https://www.wowmd.com/collections/eye-health-supplements), [digestion](https://www.wowmd.com/collections/digestion-supplements).";
const streamOf = (answer: string, sources: unknown[] = []) => [{ token: answer }, { sources }, { done: true }].map(event => `data: ${JSON.stringify(event)}\n\n`).join("");

test("playground renders the reported Markdown while preserving literal user input", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await mockPlayground(page, streamOf(productAnswer));
  await ask(page, "**Keep my input literal**");
  const answer = page.locator(".justify-start [data-answer-markdown]");
  await expect(answer.locator("li")).toHaveCount(3);
  await expect(answer.locator("strong a").first()).toHaveText("Joint Support");
  await expect(answer.getByRole("link", { name: "Turmeric Boost", exact: true })).toHaveAttribute("href", "https://www.wowmd.com/products/turmeric-boost");
  await expect(answer.getByRole("link", { name: "eye health", exact: true })).toHaveAttribute("rel", "noopener noreferrer");
  await expect(answer).not.toContainText("**");
  await expect(page.locator(".justify-end p")).toHaveText("**Keep my input literal**");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath("markdown-playground-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.locator("aside.workspace-sidebar").evaluate(element => element.getBoundingClientRect().right)).toBeLessThanOrEqual(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath("markdown-playground-mobile.png"), fullPage: true });
  await answer.screenshot({ path: testInfo.outputPath("markdown-playground-mobile-answer.png") });
});

test("playground restricts verified links and never executes answer HTML or loads images", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", request => requests.push(request.url()));
  await mockPlayground(page, streamOf("**Safe** [verified](https://www.wowmd.com/products/joint-support) [unverified](https://bad.invalid) [script](javascript:alert%281%29) ![blocked image](https://bad.invalid/pixel.png)\n\n<script>window.markdownExecuted=true</script>\n\n<img src=x onerror=alert(1)>", [{ document_id: 1, filename: "Joint Support", source_url: "https://www.wowmd.com/products/joint-support", chunk_refs: [] }]));
  await ask(page);
  const answer = page.locator(".justify-start [data-answer-markdown]");
  await expect(answer.locator("strong")).toHaveText("Safe");
  await expect(answer.locator("a")).toHaveCount(1);
  await expect(answer.locator("img,script")).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { markdownExecuted?: boolean }).markdownExecuted)).toBeUndefined();
  expect(requests.some(url => url.includes("bad.invalid"))).toBe(false);
});

test("shared transcript formats stored assistant Markdown and leaves the question plain", async ({ page }) => {
  await mockPlayground(page);
  await page.route("**/public/share/markdown-test", route => {
    if (route.request().resourceType() === "document") return route.continue();
    return route.fulfill({ json: { session: { title: "Markdown snapshot", bot_name: "Synthetic bot", created_at: "2026-10-12" }, messages: [{ id: 1, user_message: "**Literal question**", assistant_response: productAnswer, created_at: "2026-10-12" }] } });
  });
  await page.goto("/public/share/markdown-test");
  await expect(page.locator("[data-answer-markdown] li")).toHaveCount(3);
  await expect(page.getByRole("link", { name: "Joint Support", exact: true })).toHaveAttribute("target", "_blank");
  await expect(page.getByText("**Literal question**", { exact: true })).toBeVisible();
});

test("conversation history formats the stored answer without changing its content", async ({ page }) => {
  await mockPlayground(page);
  const session = { id: 4, bot_id: 7, bot_name: "Synthetic bot", organization_id: 9, session_id: "markdown-session", title: "Stored Markdown", is_pinned: false, is_archived: false, shared_token: null, channel: "dashboard", status: "open", tags: [], created_at: "2026-10-12", updated_at: "2026-10-12" };
  await page.route(/\/organizations\/9\/conversations(?:\/markdown-session)?(?:\?.*)?$/, route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith("/markdown-session") ? { session, messages: [{ id: 1, user_message: "**Literal question**", assistant_response: productAnswer, response_time_ms: 1000, status: "completed", is_fallback: false, had_knowledge_hit: true, created_at: "2026-10-12" }] } : [session] }));
  await page.route("**/bots*", route => route.fulfill({ json: [{ id: 7, organization_id: 9, name: "Synthetic bot" }] }));
  await page.goto("/conversations");
  await page.getByRole("button", { name: "Stored Markdown", exact: true }).click();
  await expect(page.locator("[data-answer-markdown] li")).toHaveCount(3);
  await expect(page.getByRole("link", { name: "Joint Support", exact: true })).toHaveAttribute("href", "https://www.wowmd.com/products/joint-support");
  await expect(page.getByText("**Literal question**", { exact: true })).toBeVisible();
});
