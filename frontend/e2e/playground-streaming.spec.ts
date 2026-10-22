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
async function ask(page: Page) {
  await page.goto("/knowledge/7");
  await expect(page.getByRole("heading", { name: "Synthetic bot", exact: true })).toBeVisible();
  await page.getByPlaceholder("Ask about uploaded docs or crawled pages...").fill("Synthetic question");
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
