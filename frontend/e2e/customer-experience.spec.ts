import { expect, test, type Page } from "@playwright/test";

// Render the actual dashboard while isolating it from customer data and AI calls.
async function mockExperience(page: Page, role = "editor") {
  const calls: Array<{ method: string; path: string; body: Record<string, unknown> | null; organization?: string }> = [];
  let settings = { enabled: false, suggested_questions: [], hosted_chat_enabled: false, lead_form_enabled: false, approved_faq_enabled: false, product_cards_enabled: false, lead_consent_text: "I agree to be contacted about my request.", font_family: "serif", density: "comfortable", theme: "dark", corner_style: "soft" };
  const faqs: Record<string, unknown>[] = [];
  const products: Record<string, unknown>[] = [];
  let integrations = { booking: { provider: "none", enabled: false, url: "", label: "Book an appointment" }, orders: { provider: "none", enabled: false, url: "", label: "Track an order" } };
  const question = { id: 4, question: "What is the example opening time?", expected_answer: "Open at 9 am.", required_phrases: ["9 am"], forbidden_phrases: [], enabled: true };
  let run: Record<string, unknown> | null = null;
  const timestamp = "2026-10-12T12:00:00Z";
  await page.addInitScript((accessRole) => localStorage.setItem("chatbot-saas-auth", JSON.stringify({ state: { selectedOrganizationId: "9", activeOrganizationRole: accessRole, user: { id: "1", name: "Test editor", email: "editor@example.test" } }, version: 0 })), role);
  await page.route("**/*", async (route) => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname;
    if (!["fetch", "xhr"].includes(request.resourceType()) || path.startsWith("/_next") || url.searchParams.has("_rsc")) return route.continue();
    const method = request.method(); const body = request.postData() ? request.postDataJSON() as Record<string, unknown> : null;
    calls.push({ method, path, body, organization: request.headers()["x-organization-id"] });
    const respond = (data: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (path === "/auth/refresh") return respond({ access_token: "synthetic-access", user: { id: 1, name: "Test editor", email: "editor@example.test", is_admin: false } });
    if (path === "/organizations/") return respond([{ id: 9, name: "Example workspace", slug: "example", role, created_at: timestamp }]);
    if (path === "/bot/7") return respond({ id: 7, organization_id: 9, name: "Example bot", status: "active", provider: "gemini", model_name: "models/gemini-3.5-flash-lite", allowed_origins: [], created_at: timestamp });
    if (path === "/knowledge/documents") return respond({ documents: [] });
    if (path === "/bots") return respond([]);
    if (path === "/bot/7/experience/") return respond(settings);
    if (path === "/bot/7/experience/settings") { settings = { ...settings, ...body }; return respond(settings); }
    if (path === "/bot/7/experience/faqs") {
      if (method === "POST") { const entry = { ...body, id: 1, source_status: "unbound", created_at: timestamp, updated_at: timestamp }; faqs.push(entry); return respond(entry); }
      return respond({ items: faqs });
    }
    if (path === "/bot/7/experience/products") {
      if (method === "POST") { const entry = { ...body, id: 1, created_at: timestamp, updated_at: timestamp }; products.push(entry); return respond(entry); }
      return respond({ items: products });
    }
    if (path === "/bot/7/experience/integrations") { if (method === "PUT") integrations = body as unknown as typeof integrations; return respond(integrations); }
    if (path === "/bot/7/experience/leads") return respond({ items: [{ id: 1, name: "Example customer", email: "customer@example.test", phone: null, message: "Please contact me.", status: "new", created_at: timestamp, consent_at: timestamp }], total: 1 });
    if (path === "/bot/7/experience/leads/1" && method === "PATCH") return respond({ id: 1, ...body });
    if (path === "/bot/7/experience/test-cases") return respond({ items: [question] });
    if (path === "/bot/7/experience/test-runs") {
      if (method === "POST") { run = { id: 2, status: "pending", created_at: timestamp, completed_at: null, results: [{ id: 3, case_id: 4, question: question.question, expected_answer: question.expected_answer, status: "pending", answer: null, latency_ms: null, missing_phrases: [], forbidden_matches: [], error: null, sources: [] }] }; return respond(run); }
      return respond({ items: run ? [run] : [] });
    }
    if (path === "/bot/7/experience/test-runs/2") return respond(run);
    if (path === "/bot/7/experience/test-runs/2/execute-next") { run = { ...run, status: "completed", completed_at: timestamp, results: [{ id: 3, case_id: 4, question: question.question, expected_answer: question.expected_answer, status: "passed_checks", answer: "**We open** at 9 am.", latency_ms: 3200, missing_phrases: [], forbidden_matches: [], error: null, sources: [] }] }; return respond(run); }
    return respond({ detail: "Outside isolated dashboard UI test." }, 503);
  });
  await page.goto("/bots/7?tab=experience");
  await expect(page.getByRole("heading", { name: "Customer experience", exact: true })).toBeVisible();
  return calls;
}

test("experience settings preserve appearance and send organization scope", async ({ page }) => {
  const calls = await mockExperience(page);
  await page.getByLabel("Enable customer experience features", { exact: false }).check();
  await page.getByLabel("Standalone chat link", { exact: false }).check();
  await page.getByLabel("Suggested questions", { exact: false }).fill("What can you help me with?\nWhere can I contact you?");
  await page.getByRole("button", { name: "Save settings", exact: true }).click();
  await expect(page.getByRole("link", { name: "Open chat", exact: true })).toHaveAttribute("href", /\/chat\/7$/);
  const call = calls.find((item) => item.method === "PUT" && item.path.endsWith("/settings"));
  expect(call?.organization).toBe("9");
  expect(call?.body).toMatchObject({ enabled: true, hosted_chat_enabled: true, theme: "dark", font_family: "serif", suggested_questions: ["What can you help me with?", "Where can I contact you?"] });
});

test("FAQ approval saves reviewed text and explicit aliases without changing bot settings", async ({ page }) => {
  const calls = await mockExperience(page);
  await page.getByRole("button", { name: "Approved answers", exact: true }).click();
  await page.getByLabel("Question", { exact: true }).fill("What is your opening time?");
  await page.getByLabel("Approved answer", { exact: true }).fill("Our office opens at 9 am.");
  await page.getByLabel("Alternative question wordings", { exact: false }).fill("When do you open?\nWhat time is opening?");
  await page.getByLabel("I have reviewed and approve this answer", { exact: false }).check();
  await page.getByRole("button", { name: "Save answer", exact: true }).click();
  await expect(page.getByRole("heading", { name: "What is your opening time?", exact: true })).toBeVisible();
  expect(calls.find((item) => item.method === "POST" && item.path.endsWith("/faqs"))?.body).toMatchObject({ question: "What is your opening time?", answer: "Our office opens at 9 am.", aliases: ["When do you open?", "What time is opening?"], approved: true, source_document_id: null });
  expect(calls.some((item) => item.path === "/bot/7" && item.method !== "GET")).toBe(false);
});

test("integration controls expose only saved live destinations", async ({ page }) => {
  const calls = await mockExperience(page);
  await page.getByRole("button", { name: "Booking & orders", exact: true }).click();
  await expect(page.getByRole("link", { name: "Test saved link", exact: true })).toHaveCount(0);
  await page.getByRole("combobox", { name: "Booking provider", exact: true }).selectOption("calcom");
  await page.getByLabel("Public booking page", { exact: false }).fill("https://cal.com/example/consultation");
  await page.getByLabel("Show booking button", { exact: true }).check();
  await page.getByRole("button", { name: "Save integrations", exact: true }).click();
  await expect(page.getByRole("link", { name: "Test saved link", exact: true })).toHaveAttribute("href", "https://cal.com/example/consultation");
  expect(calls.find((item) => item.method === "PUT" && item.path.endsWith("/integrations"))?.body).toMatchObject({ booking: { provider: "calcom", enabled: true, url: "https://cal.com/example/consultation" }, orders: { enabled: false } });
});

test("saved test uses selected cases and shows actual answer, reference and timing", async ({ page }) => {
  const calls = await mockExperience(page);
  await page.getByRole("button", { name: "Saved tests", exact: true }).click();
  await page.getByRole("button", { name: "Select up to 30", exact: true }).click();
  await page.getByRole("button", { name: "Run 1 question", exact: true }).click();
  await expect(page.getByText("Run 2 · 1 / 1 finished", { exact: true })).toBeVisible();
  await page.locator("summary").filter({ hasText: "What is the example opening time?" }).click();
  await expect(page.getByText("We open at 9 am.", { exact: true })).toBeVisible();
  await expect(page.locator("[data-answer-markdown] strong")).toHaveText("We open");
  await expect(page.getByText("Open at 9 am.", { exact: true })).toBeVisible();
  await expect(page.locator("summary")).toContainText("3.20s");
  expect(calls.find((item) => item.method === "POST" && item.path.endsWith("/test-runs"))?.body).toEqual({ case_ids: [4] });
  expect(calls.filter((item) => item.path.endsWith("/execute-next"))).toHaveLength(1);
});

async function mockDurableRun(page: Page) {
  await mockExperience(page);
  await page.clock.install();
  const timestamp = "2026-10-23T12:00:00Z";
  const questions = [4, 5].map((id) => ({ id, question: `Synthetic durable question ${id}?`, expected_answer: "Grounded fixture answer.", required_phrases: [], forbidden_phrases: [], enabled: true }));
  const state = { posts: 0, polls: 0, failRead: false, created: false, run: {
    id: 2, status: "pending", created_at: timestamp, completed_at: null as string | null, provider: "gemini", model: "synthetic",
    results: questions.map((question) => ({ id: question.id + 10, case_id: question.id, question: question.question, expected_answer: question.expected_answer, status: "pending", answer: null as string | null, latency_ms: null as number | null, missing_phrases: [], forbidden_matches: [], error: null, sources: [] })),
  } };
  const settle = (index: number) => {
    Object.assign(state.run.results[index], { status: "passed_checks", answer: "Grounded fixture answer.", latency_ms: 25000 });
    if (state.run.results.every((result) => result.status === "passed_checks")) Object.assign(state.run, { status: "completed", completed_at: timestamp });
  };
  await page.route(/\/bot\/7\/experience\/test-/, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/test-cases")) return route.fulfill({ json: { items: questions } });
    if (path.endsWith("/test-runs")) {
      if (route.request().method() === "POST") { state.created = true; return route.fulfill({ json: state.run }); }
      return route.fulfill({ json: { items: state.created ? [state.run] : [] } });
    }
    if (path.endsWith("/execute-next")) {
      state.posts++;
      const next = state.run.results.find((result) => result.status === "pending");
      if (next) next.status = "running";
      state.run.status = "running";
      return route.fulfill({ json: state.run });
    }
    if (path.endsWith("/2")) { state.polls++; return route.fulfill({ status: state.failRead ? 503 : 200, json: state.failRead ? { detail: "Synthetic polling failure" } : state.run }); }
    return route.fulfill({ status: 503, json: { detail: "Unexpected saved-run request" } });
  });
  await page.getByRole("button", { name: "Saved tests", exact: true }).click();
  await page.getByRole("button", { name: "Select up to 30", exact: true }).click();
  await page.getByRole("button", { name: "Run 2 questions", exact: true }).click();
  await expect.poll(() => state.posts).toBe(1);
  await expect(page.locator("summary").first()).toContainText("Running");
  return { state, settle };
}

test("durable saved tests poll an accepted answer and dispatch the next only after settlement", async ({ page }) => {
  const { state, settle } = await mockDurableRun(page);
  await page.clock.fastForward(3000);
  await expect.poll(() => state.polls).toBe(1);
  expect(state.posts).toBe(1);
  settle(0);
  await page.clock.fastForward(3000);
  await expect.poll(() => state.posts).toBe(2);
  settle(1);
  await page.clock.fastForward(3000);
  await expect(page.getByText("Run 2 · 2 / 2 finished", { exact: true })).toBeVisible();
  expect(state.posts).toBe(2);
});

test("pause waits for the durable answer to save and resumes from a fresh GET", async ({ page }) => {
  const { state, settle } = await mockDurableRun(page);
  await page.getByRole("button", { name: "Pause after this question", exact: true }).click();
  settle(0);
  await page.clock.fastForward(3000);
  await expect(page.getByRole("button", { name: "Resume run", exact: true })).toBeVisible();
  expect(state.posts).toBe(1);
  expect(state.polls).toBe(1);
  await page.getByRole("button", { name: "Resume run", exact: true }).click();
  await expect.poll(() => state.posts).toBe(2);
  expect(state.polls).toBe(2);
  settle(1);
  await page.clock.fastForward(3000);
  await expect(page.getByText("Run 2 · 2 / 2 finished", { exact: true })).toBeVisible();
});

test("leaving saved tests stops polling while the durable answer remains resumable", async ({ page }) => {
  const { state, settle } = await mockDurableRun(page);
  await page.getByRole("button", { name: "Settings & sharing", exact: true }).click();
  await page.clock.fastForward(15000);
  expect(state.polls).toBe(0);
  expect(state.posts).toBe(1);
  await page.getByRole("button", { name: "Saved tests", exact: true }).click();
  await page.getByRole("combobox", { name: "Choose a saved run", exact: false }).selectOption("2");
  await page.getByRole("button", { name: "Resume run", exact: true }).click();
  await expect.poll(() => state.polls).toBe(2); // Opening the saved run and refreshing before resume.
  expect(state.posts).toBe(1);
  settle(0);
  await page.clock.fastForward(3000);
  await expect.poll(() => state.posts).toBe(2);
});

test("polling failure preserves saved results and does not resubmit the active question", async ({ page }) => {
  const { state, settle } = await mockDurableRun(page);
  state.failRead = true;
  await page.clock.fastForward(3000);
  await expect(page.getByText(/Saved results are retained\. Refresh the run before resuming\./)).toBeVisible();
  await page.clock.fastForward(15000);
  expect(state.posts).toBe(1);
  state.failRead = false;
  settle(0); settle(1);
  await page.getByRole("button", { name: "Resume run", exact: true }).click();
  await expect(page.getByText("Run 2 · 2 / 2 finished", { exact: true })).toBeVisible();
  expect(state.posts).toBe(1);
});

test("viewer can inspect settings but cannot edit or see contacts", async ({ page }) => {
  const calls = await mockExperience(page, "viewer");
  await expect(page.getByLabel("Enable customer experience features", { exact: false })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Save settings", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Leads & contacts", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Approved answers", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Add an answer", exact: true })).toHaveCount(0);
  expect(calls.some((item) => item.method === "PUT" || item.method === "PATCH" || item.method === "DELETE")).toBe(false);
});

test("mobile bot and feature navigation fit the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockExperience(page);
  await expect(page.getByRole("button", { name: "Saved tests", exact: true })).toBeVisible();
  const size = await page.evaluate(() => ({ width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
  expect(size.scroll).toBeLessThanOrEqual(size.width + 1);
});

test("dashboard shortcut menu supports keyboard navigation to a real page", async ({ page }) => {
  await mockExperience(page);
  const trigger = page.getByRole("button", { name: "Find in dashboard", exact: true });
  await trigger.focus();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("menuitem", { name: "Bots", exact: true })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/bots$/);
  await expect(page.getByRole("button", { name: /Switch to .* theme/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Account menu", exact: true })).toBeVisible();
});
