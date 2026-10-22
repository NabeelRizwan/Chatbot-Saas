import { expect, test, type Page } from "@playwright/test";

// Real rendered Next/React UI, deterministic intercepted API. No accounts,
// credentials, provider calls, or customer database changes are made.
const providerOptions = { providers: [
  { id: "gemini", models: ["gemini-2.5-flash", "gemini-1.5-pro"] },
  { id: "openai", models: ["gpt-4.1-mini", "gpt-4.1"] },
  { id: "claude", models: ["claude-3-5-sonnet"] },
  { id: "grok", models: ["grok-2"] },
], allocation_mode: "bot_capacity_pool" };
const profile = (id: number, provider = "gemini", status = "available", assigned = 0) => ({
  id, credential_profile_id: id, provider, label: `${provider} profile ${id}`, status,
  max_bot_assignments: 2, remaining_capacity: Math.max(0, 2 - assigned), assigned_bot_count: assigned,
  assigned_bots: Array.from({ length: assigned }, (_, i) => ({ id: 90 + i, name: `Assigned bot ${i}`, provider, model_name: "gemini-2.5-flash", organization_id: 20 + i, organization_name: `Organization ${i}`, customer_name: `Customer ${i}` })),
  assigned_bots_limit: 10,
  created_at: "2026-09-01T00:00:00", updated_at: "2026-09-01T00:00:00",
  // Deliberately injected to prove the renderer only displays safe fields.
  api_key: "synthetic-should-not-render", encrypted_key: "synthetic-ciphertext-should-not-render",
});
const initialBot = { id: 7, name: "Example bot", organization_id: 9, organization_name: "Example organization", customer_name: "Example customer", status: "active", provider: "gemini", model_name: "gemini-2.5-flash", usage_mode: "platform", credential_profile_id: null, credential_label: null, credential_status: null, credential_assigned_bot_count: null, credential_max_bot_assignments: null, credential_remaining_capacity: null };

async function mockApi(page: Page, admin = true) {
  const calls: { method: string; path: string; body: Record<string, unknown> | null }[] = [];
  let keys = [profile(1), profile(2, "openai"), profile(3, "gemini", "disabled"), profile(4, "gemini", "assigned", 2), profile(5, "gemini", "assigned", 1)];
  let bot: Record<string, unknown> = { ...initialBot };
  let accountDisabled = false;
  const plans = [
    { id: 1, code: "free", name: "Free", active: true, monthly_price_cents: 0, limits_json: { max_bots: 2, max_documents: 20, monthly_messages: 500, storage_bytes: 52428800, team_members: 2 } },
    { id: 2, code: "pro", name: "Pro", active: true, monthly_price_cents: 2900, limits_json: { max_bots: 10, max_documents: 500, monthly_messages: 10000, storage_bytes: 1073741824, team_members: 5 } },
  ];
  let assignedPlan = 1;
  let knowledgePipeline = { organization_id: 9, pipeline: "og", revision: 2 };
  await page.route("**/*", async (route) => {
    const req = route.request(); const url = new URL(req.url()); const path = url.pathname;
    if (!["fetch", "xhr"].includes(req.resourceType()) || path.startsWith("/_next") || url.searchParams.has("_rsc")) return route.continue();
    const method = req.method();
    const body = req.postData() ? req.postDataJSON() as Record<string, unknown> : null;
    calls.push({ method, path, body });
    const respond = (data: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (path === "/auth/refresh") return respond({ access_token: "synthetic-access", user: { id: 1, name: "Operator", email: "operator@example.test", is_admin: admin } });
    if (path === "/admin/session") return respond(admin ? { user_id: 1, is_admin: true } : { detail: "Platform administrator privileges required." }, admin ? 200 : 403);
    if (path === "/admin/users/2/status") { accountDisabled = Boolean(body?.disabled); return respond({ id: 2, name: "Example user", email: "example@example.test", disabled: accountDisabled, is_admin: false }); }
    if (path === "/admin/users") return respond({ items: [{ id: 2, name: "Example user", email: "example@example.test", disabled: accountDisabled, is_admin: false, password_hash: "must-never-render" }], total: 1, offset: 0, limit: 25 });
    if (path === "/admin/plans") return respond(plans);
    if (path === "/admin/plans/1/limits") { plans[0].limits_json = { ...plans[0].limits_json, ...(body?.limits as object) }; return respond(plans[0]); }
    if (path === "/admin/organizations/9/plan") { if (method === "PATCH") assignedPlan = Number(body?.plan_id); return respond(plans.find((plan) => plan.id === assignedPlan)); }
    if (path === "/billing/organizations/9/usage") return respond({ organization_id: 9, month: "2026-09", current_plan: plans[assignedPlan - 1].code, usage: { documents_used: 3, knowledge_resources_reserved: 0, messages_used: 4 }, limits: plans[assignedPlan - 1].limits_json, current_period: { start: "2026-09-01", end: null }, metering: {}, subscription_status: "active" });
    if (path === "/admin/audit-logs") return respond({ items: [{ id: 1, user_id: 1, organization_id: 9, action: "platform.organization.plan_assigned:plan:2", created_at: "2026-09-01T00:00:00", api_key: "must-never-render" }], total: 1, offset: 0, limit: 25 });
    if (path === "/admin/provider-options") return respond(providerOptions);
    if (path === "/admin/overview") return respond({ organizations: 2, bots: 3, enabled_credentials: 4 });
    if (path === "/admin/organizations") return respond({ items: [{ id: 9, name: "Example organization", bot_count: 1, created_at: "2026-09-01" }], total: 1, offset: 0, limit: 25 });
    if (path === "/admin/organizations/9/knowledge-pipeline") {
      if (method === "PATCH") {
        const expected = body?.expected as { pipeline: string; revision: number };
        if (expected.pipeline !== knowledgePipeline.pipeline || expected.revision !== knowledgePipeline.revision) return respond({ detail: "Pipeline changed elsewhere." }, 409);
        if (body?.pipeline !== knowledgePipeline.pipeline) knowledgePipeline = { ...knowledgePipeline, pipeline: String(body?.pipeline), revision: knowledgePipeline.revision + 1 };
      }
      return respond(knowledgePipeline);
    }
    if (path === "/admin/bots") return respond({ items: [bot], total: 1, offset: 0, limit: 25 });
    if (path.endsWith("/provider-config")) { bot = { ...bot, ...body }; return respond(bot); }
    if (path === "/admin/platform-keys" && method === "GET") return respond({ items: keys, total: keys.length, offset: 0, limit: 25 });
    if (path === "/admin/platform-keys" && method === "POST") {
      const added = { ...profile(10, String(body?.provider)), label: String(body?.label), max_bot_assignments: Number(body?.max_bot_assignments) };
      keys = [...keys, added]; return respond(added, 201);
    }
    if (method === "PUT" && path.startsWith("/admin/platform-keys/")) {
      const key = keys.find((key) => key.id === Number(path.split("/").at(-1)))!;
      const capacity = Number(body?.max_bot_assignments);
      if (capacity < key.assigned_bot_count) return respond({ detail: `Cannot lower capacity below ${key.assigned_bot_count} currently assigned bots.` }, 409);
      Object.assign(key, { max_bot_assignments: capacity, remaining_capacity: capacity - key.assigned_bot_count });
      return respond(key);
    }
    if (method === "POST" && path.endsWith("/disable")) {
      const key = keys.find((key) => key.id === Number(path.split("/").at(-2)))!;
      key.status = "disabled"; return respond(key);
    }
    if (method === "DELETE" && path.startsWith("/admin/platform-keys/")) { keys = keys.filter((key) => key.id !== Number(path.split("/").at(-1))); return respond({ success: true }); }
    if (path === "/bots" || path === "/bot" || path === "/organizations") return respond([]);
    // No unexpected network request may reach a real backend/provider.
    return respond({ detail: "Not part of the isolated admin UI test." }, 503);
  });
  return calls;
}

test("admin navigation and overview use authenticated API state", async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Platform admin", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Admin", exact: true })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Admin navigation" })).toBeVisible();
  expect(calls.some((call) => call.path === "/admin/session")).toBeTruthy();
  for (const section of ["Organizations", "Bots", "Knowledge", "Users", "Plans / Usage", "API Credentials", "System / Audit"]) {
    await expect(page.getByRole("navigation", { name: "Admin navigation" }).getByRole("link", { name: section, exact: true })).toBeVisible();
  }
});

test("knowledge management opens the correct existing workspace", async ({ page }) => {
  await mockApi(page);
  await page.goto("/admin/knowledge");
  const link = page.getByRole("link", { name: "Manage knowledge", exact: true });
  await expect(link).toHaveAttribute("href", "/knowledge/7");
  await link.click();
  await expect(page).toHaveURL(/\/knowledge\/7$/);
  const selected = await page.evaluate(() => JSON.parse(localStorage.getItem("chatbot-saas-auth") || "{}").state.selectedOrganizationId);
  expect(selected).toBe("9");
});

test("user status is saved through admin API and private fields never render", async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto("/admin/users");
  await expect(page.getByText("example@example.test", { exact: false })).toBeVisible();
  await expect(page.locator("body")).not.toContainText("must-never-render");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Disable", exact: true }).click();
  await expect(page.getByRole("button", { name: "Enable", exact: true })).toBeVisible();
  expect(calls.find((call) => call.path === "/admin/users/2/status")?.body).toEqual({ disabled: true, expected_disabled: false });
});

test("organization plan changes preserve explicit scope and refresh usage", async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto("/admin/plans?organization_id=9");
  await expect(page.getByText("Knowledge: 3 / 20", { exact: false })).toBeVisible();
  await page.getByRole("combobox", { name: "Assign plan", exact: true }).selectOption("2");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Save organization plan", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Organization plan saved.");
  await expect(page.getByText("Knowledge: 3 / 500", { exact: false })).toBeVisible();
  expect(calls.find((call) => call.path === "/admin/organizations/9/plan" && call.method === "PATCH")?.body).toEqual({ plan_id: 2, expected_plan_id: 1 });
});

test("shared limit edit confirms global impact and audit renders only public fields", async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto("/admin/plans");
  await page.getByRole("button", { name: "Edit limits", exact: true }).first().click();
  await page.getByLabel("Knowledge resources", { exact: true }).fill("150");
  page.once("dialog", async (dialog) => { expect(dialog.message()).toContain("EVERY organization"); await dialog.accept(); });
  await page.getByRole("button", { name: "Save shared limits", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Plan limits saved.");
  const save = calls.find((call) => call.path === "/admin/plans/1/limits");
  expect((save?.body?.limits as Record<string, number>).max_documents).toBe(150);
  expect((save?.body?.expected_limits as Record<string, number>).max_documents).toBe(20);
  await page.getByRole("link", { name: "System / Audit", exact: true }).click();
  await expect(page.getByText("platform.organization.plan_assigned:plan:2")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("must-never-render");
});

test("forged cached admin flag cannot open admin or show admin navigation", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("chatbot-saas-auth", JSON.stringify({ state: { user: { id: "1", name: "Cached", email: "cached@example.test", is_admin: true } }, version: 0 })));
  await mockApi(page, false);
  await page.goto("/admin/api-credentials");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("link", { name: "Admin", exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Add API credential" })).toHaveCount(0);
});

test("credential form clears saved secret and list renders metadata only", async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto("/admin/api-credentials");
  await expect(page.getByLabel("Maximum bot assignments", { exact: true })).toHaveValue("2");
  await page.getByLabel("Label", { exact: true }).fill("Secondary profile");
  await page.getByLabel("API secret", { exact: true }).fill("synthetic-new-secret-only");
  await page.getByRole("button", { name: "Save credential", exact: true }).click();
  await expect(page.getByLabel("API secret", { exact: true })).toHaveValue("");
  await expect(page.getByRole("status")).toContainText("Credential saved");
  expect(calls.find((call) => call.path === "/admin/platform-keys" && call.method === "POST")?.body?.api_key).toBe("synthetic-new-secret-only");
  expect(calls.find((call) => call.path === "/admin/platform-keys" && call.method === "POST")?.body?.max_bot_assignments).toBe(2);
  await expect(page.locator("body")).not.toContainText("synthetic-should-not-render");
  await expect(page.locator("body")).not.toContainText("synthetic-ciphertext-should-not-render");
  const storage = await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]));
  expect(storage).not.toContain("synthetic-new-secret-only");
});

test("destructive profile action requires confirmation", async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto("/admin/api-credentials");
  const row = page.getByRole("row").filter({ hasText: "gemini profile 1" });
  page.once("dialog", (dialog) => dialog.dismiss());
  await row.getByRole("button", { name: "Delete", exact: true }).click();
  expect(calls.some((call) => call.method === "DELETE")).toBeFalsy();
  page.once("dialog", (dialog) => dialog.accept());
  await row.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(row).toHaveCount(0);
  expect(calls.filter((call) => call.method === "DELETE")).toHaveLength(1);
});

test("bot selector filters provider, disabled and full profiles but includes shared capacity; saves a snapshot", async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto("/admin/bots");
  await page.getByRole("button", { name: "Configure", exact: true }).click();
  const selector = page.getByRole("combobox", { name: "Credential profile", exact: true });
  await expect(selector).toContainText("gemini profile 1");
  await expect(selector).not.toContainText("openai profile 2");
  await expect(selector).not.toContainText("gemini profile 3");
  await expect(selector).not.toContainText("gemini profile 4");
  await expect(selector).toContainText("gemini profile 5");
  await page.getByRole("combobox", { name: "Generation provider", exact: true }).selectOption("openai");
  await expect(selector).toContainText("openai profile 2");
  await selector.selectOption("2");
  await page.getByRole("button", { name: "Save generation settings", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Generation settings saved");
  const saved = calls.find((call) => call.path.endsWith("/provider-config"));
  expect(saved?.body).toEqual({ provider: "openai", model_name: "gpt-4.1-mini", credential_profile_id: 2, expected: { provider: "gemini", model_name: "gemini-2.5-flash", credential_profile_id: null } });
});

test("rejected save shows actionable error without a success message", async ({ page }) => {
  await mockApi(page);
  await page.route("**/admin/platform-keys", (route) => route.request().method() === "POST" ? route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "Choose a supported generation provider." }) }) : route.fallback());
  await page.goto("/admin/api-credentials");
  await page.getByLabel("Label", { exact: true }).fill("Example");
  await page.getByLabel("API secret", { exact: true }).fill("synthetic-rejected-secret");
  await page.getByRole("button", { name: "Save credential", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Choose a supported generation provider." })).toBeVisible();
  await expect(page.locator("body")).not.toContainText("Credential saved.");
});

test("capacity edit sends expected snapshot and shows capacity after reload", async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto("/admin/api-credentials");
  const row = page.getByRole("row").filter({ hasText: "gemini profile 5" });
  await expect(row).toContainText("1 / 2 bots");
  await expect(row).toContainText("Assigned bot 0");
  page.once("dialog", (dialog) => dialog.accept("3"));
  await row.getByRole("button", { name: "Edit capacity", exact: true }).click();
  await expect(row).toContainText("1 / 3 bots");
  expect(calls.find((call) => call.method === "PUT")?.body).toEqual({ max_bot_assignments: 3, expected_max_bot_assignments: 2 });
});

test("capacity below assignments shows error and preserves original count", async ({ page }) => {
  await mockApi(page);
  await page.goto("/admin/api-credentials");
  const row = page.getByRole("row").filter({ hasText: "gemini profile 4" });
  page.once("dialog", (dialog) => dialog.accept("1"));
  await row.getByRole("button", { name: "Edit capacity", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Cannot lower capacity below 2" })).toBeVisible();
  await expect(row).toContainText("2 / 2 bots");
  await expect(page.locator("body")).not.toContainText("Credential updated.");
});

test("disable preserves visible assignments and cannot enable deletion", async ({ page }) => {
  await mockApi(page);
  await page.goto("/admin/api-credentials");
  const row = page.getByRole("row").filter({ hasText: "gemini profile 4" });
  page.once("dialog", (dialog) => { expect(dialog.message()).toContain("Assignments are retained"); return dialog.accept(); });
  await row.getByRole("button", { name: "Disable", exact: true }).click();
  await expect(row.getByRole("button", { name: "Enable", exact: true })).toBeVisible();
  await expect(row).toContainText("2 / 2 bots");
  await expect(row.getByRole("button", { name: "Delete", exact: true })).toBeDisabled();
});

const pipelinePath = "/admin/organizations/9/knowledge-pipeline";
const pipelineEditor = (page: Page) => page.getByRole("region", { name: "Knowledge pipeline", exact: true });
async function openPipeline(page: Page) {
  await page.goto("/admin/organizations");
  await page.getByRole("button", { name: "Configure pipeline for Example organization", exact: true }).click();
  return pipelineEditor(page);
}
function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}
async function mockSecondOrganization(page: Page) {
  await page.route("**/admin/organizations?*", (route) => route.fulfill({ json: { items: [
    { id: 9, name: "Example organization", bot_count: 1, created_at: "2026-09-01" },
    { id: 10, name: "Second organization", bot_count: 3, created_at: "2026-09-02" },
  ], total: 2, offset: 0, limit: 25 } }));
  await page.route("**/admin/organizations/10/knowledge-pipeline", (route) => route.fulfill({ json: { organization_id: 10, pipeline: "rag2_improved", revision: 8 } }));
}

test("organization pipeline uses saved value, explicit scope and revision, then reads back the save", async ({ page }) => {
  const calls = await mockApi(page);
  const editor = await openPipeline(page);
  const select = editor.getByRole("combobox", { name: "Pipeline for this organization", exact: true });
  await expect(editor).toContainText("Example organization · Organization #9 · 1 bot");
  await expect(editor).toContainText("Current pipeline: OG");
  await expect(editor).toContainText("RAG2 Improved is the default for new organizations.");
  await expect(editor).toContainText("Requests already queued or running finish with their accepted pipeline.");
  await expect(select).toHaveValue("og");
  await expect(editor.getByRole("button", { name: "Save pipeline", exact: true })).toBeDisabled();
  await select.selectOption("rag2_improved");
  expect(calls.filter((call) => call.path === pipelinePath && call.method === "PATCH")).toHaveLength(0);
  await expect(editor).toContainText("Current pipeline: OG");
  await editor.getByRole("button", { name: "Save pipeline", exact: true }).click();
  await expect(editor.getByRole("status")).toContainText("Pipeline saved: RAG2 Improved.");
  await expect(editor).toContainText("Current pipeline: RAG2 Improved");
  expect(calls.find((call) => call.path === pipelinePath && call.method === "PATCH")?.body).toEqual({ pipeline: "rag2_improved", expected: { pipeline: "og", revision: 2 } });
  await editor.getByRole("button", { name: "Reload current pipeline", exact: true }).click();
  await expect(select).toHaveValue("rag2_improved");
  await expect(editor.getByRole("button", { name: "Save pipeline", exact: true })).toBeDisabled();
  await select.selectOption("og");
  await editor.getByRole("button", { name: "Save pipeline", exact: true }).click();
  await expect(editor.getByRole("status")).toContainText("Pipeline saved: OG.");
  expect(calls.filter((call) => call.path === pipelinePath && call.method === "PATCH").at(-1)?.body).toEqual({ pipeline: "og", expected: { pipeline: "rag2_improved", revision: 3 } });
});

test("cancel discards an unsaved pipeline without a write", async ({ page }) => {
  const calls = await mockApi(page);
  const editor = await openPipeline(page);
  await editor.getByRole("combobox", { name: "Pipeline for this organization", exact: true }).selectOption("rag2_improved");
  await editor.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(editor).toHaveCount(0);
  await page.getByRole("button", { name: "Configure pipeline for Example organization", exact: true }).click();
  await expect(editor.getByRole("combobox", { name: "Pipeline for this organization", exact: true })).toHaveValue("og");
  expect(calls.filter((call) => call.path === pipelinePath && call.method === "PATCH")).toHaveLength(0);
});

test("pipeline loading does not assume the new-organization default", async ({ page }) => {
  await mockApi(page);
  const release = deferred();
  await page.route(`**${pipelinePath}`, async (route) => {
    await release.promise;
    await route.fulfill({ json: { organization_id: 9, pipeline: "og", revision: 2 } });
  });
  const editor = await openPipeline(page);
  await expect(editor.getByRole("status")).toContainText("Loading current pipeline");
  await expect(editor.getByRole("combobox", { name: "Pipeline for this organization", exact: true })).toBeDisabled();
  await expect(editor.getByRole("button", { name: "Save pipeline", exact: true })).toBeDisabled();
  await expect(editor).not.toContainText("Current pipeline:");
  release.resolve();
  await expect(editor.getByRole("combobox", { name: "Pipeline for this organization", exact: true })).toHaveValue("og");
});

test("pending pipeline save disables actions and submits only once", async ({ page }) => {
  await mockApi(page);
  const release = deferred();
  let patches = 0;
  await page.route(`**${pipelinePath}`, async (route) => {
    if (route.request().method() !== "PATCH") return route.fallback();
    patches++;
    await release.promise;
    await route.fulfill({ json: { organization_id: 9, pipeline: "rag2_improved", revision: 3 } });
  });
  const editor = await openPipeline(page);
  await editor.getByRole("combobox", { name: "Pipeline for this organization", exact: true }).selectOption("rag2_improved");
  await editor.getByRole("button", { name: "Save pipeline", exact: true }).evaluate((element: HTMLButtonElement) => { element.click(); element.click(); });
  await expect.poll(() => patches).toBe(1);
  await expect(editor.getByRole("button", { name: "Saving…", exact: true })).toBeDisabled();
  await expect(editor.getByRole("combobox", { name: "Pipeline for this organization", exact: true })).toBeDisabled();
  await expect(editor.getByRole("button", { name: "Reload current pipeline", exact: true })).toBeDisabled();
  await expect(editor.getByRole("button", { name: "Cancel", exact: true })).toBeDisabled();
  release.resolve();
  await expect(editor.getByRole("status")).toContainText("Pipeline saved: RAG2 Improved.");
  expect(patches).toBe(1);
});

test("stale pipeline save requires reload and never overwrites a newer revision", async ({ page }) => {
  await mockApi(page);
  let stale = false;
  let patches = 0;
  await page.route(`**${pipelinePath}`, (route) => {
    if (route.request().method() === "PATCH") {
      stale = true;
      patches++;
      return route.fulfill({ status: 409, json: { detail: "Pipeline changed elsewhere." } });
    }
    return route.fulfill({ json: { organization_id: 9, pipeline: stale ? "rag2_improved" : "og", revision: stale ? 4 : 2 } });
  });
  const editor = await openPipeline(page);
  await editor.getByRole("combobox", { name: "Pipeline for this organization", exact: true }).selectOption("rag2_improved");
  await editor.getByRole("button", { name: "Save pipeline", exact: true }).click();
  await expect(editor.getByRole("alert")).toContainText("This setting changed elsewhere. Reload");
  await expect(editor).toContainText("Current pipeline: OG");
  await expect(editor.getByRole("button", { name: "Save pipeline", exact: true })).toBeDisabled();
  await expect(editor.getByRole("status")).toHaveCount(0);
  await editor.getByRole("button", { name: "Reload current pipeline", exact: true }).click();
  await expect(editor).toContainText("Current pipeline: RAG2 Improved");
  await expect(editor.getByRole("combobox", { name: "Pipeline for this organization", exact: true })).toHaveValue("rag2_improved");
  await expect(editor.getByRole("alert")).toHaveCount(0);
  expect(patches).toBe(1);
});

for (const status of [403, 422, 503]) {
  test(`pipeline save failure ${status} cannot display success or retry a stale snapshot`, async ({ page }) => {
    await mockApi(page);
    await page.route(`**${pipelinePath}`, (route) => route.request().method() === "PATCH"
      ? route.fulfill({ status, json: { detail: "The change was rejected." } }) : route.fallback());
    const editor = await openPipeline(page);
    await editor.getByRole("combobox", { name: "Pipeline for this organization", exact: true }).selectOption("rag2_improved");
    await editor.getByRole("button", { name: "Save pipeline", exact: true }).click();
    await expect(editor.getByRole("alert")).toContainText(status === 403 ? "Platform administrator access is required" : "Unable to confirm the save. Reload");
    await expect(editor).toContainText("Current pipeline: OG");
    await expect(editor.getByRole("status")).toHaveCount(0);
    await expect(editor.getByRole("button", { name: "Save pipeline", exact: true })).toBeDisabled();
  });
}

for (const status of [403, 503]) {
  test(`pipeline read failure ${status} disables editing and can be reloaded`, async ({ page }) => {
    const calls = await mockApi(page);
    let fail = true;
    await page.route(`**${pipelinePath}`, (route) => fail ? route.fulfill({ status, json: { detail: "Not available." } }) : route.fallback());
    const editor = await openPipeline(page);
    await expect(editor.getByRole("alert")).toContainText(status === 403 ? "Platform administrator access is required" : "Unable to load the current pipeline");
    await expect(editor.getByRole("combobox", { name: "Pipeline for this organization", exact: true })).toBeDisabled();
    await expect(editor.getByRole("button", { name: "Save pipeline", exact: true })).toBeDisabled();
    fail = false;
    await editor.getByRole("button", { name: "Reload current pipeline", exact: true }).click();
    await expect(editor.getByRole("combobox", { name: "Pipeline for this organization", exact: true })).toHaveValue("og");
    expect(calls.filter((call) => call.path === pipelinePath && call.method === "PATCH")).toHaveLength(0);
  });
}

test("customer with forged cached admin flag cannot load the organization pipeline", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("chatbot-saas-auth", JSON.stringify({ state: { selectedOrganizationId: "9", activeOrganizationRole: "owner", user: { id: "1", name: "Cached", email: "cached@example.test", is_admin: true } }, version: 0 })));
  const calls = await mockApi(page, false);
  await page.goto("/admin/organizations");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("button", { name: /Configure pipeline/ })).toHaveCount(0);
  expect(calls.some((call) => call.path.endsWith("/knowledge-pipeline"))).toBe(false);
});

test("late pipeline read cannot replace the selected organization's state", async ({ page }) => {
  await mockApi(page);
  await mockSecondOrganization(page);
  const started = deferred();
  const release = deferred();
  await page.route(`**${pipelinePath}`, async (route) => {
    started.resolve();
    await release.promise;
    await route.fulfill({ json: { organization_id: 9, pipeline: "og", revision: 2 } });
  });
  const editor = await openPipeline(page);
  await started.promise;
  await page.getByRole("button", { name: "Configure pipeline for Second organization", exact: true }).click();
  await expect(editor).toContainText("Second organization · Organization #10 · 3 bots");
  await expect(editor.getByRole("combobox", { name: "Pipeline for this organization", exact: true })).toHaveValue("rag2_improved");
  const response = page.waitForResponse((value) => new URL(value.url()).pathname === pipelinePath);
  release.resolve();
  await response;
  await expect(editor).toContainText("Second organization · Organization #10 · 3 bots");
  await expect(editor).toContainText("Current pipeline: RAG2 Improved");
});

test("late pipeline save cannot show success in another organization's editor", async ({ page }) => {
  await mockApi(page);
  await mockSecondOrganization(page);
  const started = deferred();
  const release = deferred();
  await page.route(`**${pipelinePath}`, async (route) => {
    if (route.request().method() !== "PATCH") return route.fallback();
    started.resolve();
    await release.promise;
    await route.fulfill({ json: { organization_id: 9, pipeline: "rag2_improved", revision: 3 } });
  });
  const editor = await openPipeline(page);
  await editor.getByRole("combobox", { name: "Pipeline for this organization", exact: true }).selectOption("rag2_improved");
  await editor.getByRole("button", { name: "Save pipeline", exact: true }).click();
  await started.promise;
  await page.getByRole("button", { name: "Configure pipeline for Second organization", exact: true }).click();
  await expect(editor).toContainText("Second organization · Organization #10 · 3 bots");
  await expect(editor.getByRole("combobox", { name: "Pipeline for this organization", exact: true })).toHaveValue("rag2_improved");
  const response = page.waitForResponse((value) => new URL(value.url()).pathname === pipelinePath && value.request().method() === "PATCH");
  release.resolve();
  await response;
  await expect(editor.getByRole("status")).toHaveCount(0);
  await expect(editor.getByRole("button", { name: "Save pipeline", exact: true })).toBeDisabled();
  await expect(editor).toContainText("Second organization · Organization #10 · 3 bots");
});

for (const width of [390, 1440]) {
  test(`organization pipeline controls fit a ${width}px viewport`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApi(page);
    const editor = await openPipeline(page);
    await expect(editor.getByRole("combobox", { name: "Pipeline for this organization", exact: true })).toHaveValue("og");
    const dimensions = await editor.evaluate((element) => ({ width: element.getBoundingClientRect().width, left: element.getBoundingClientRect().left, right: element.getBoundingClientRect().right, scroll: element.scrollWidth, client: element.clientWidth }));
    expect(dimensions.left).toBeGreaterThanOrEqual(0);
    expect(dimensions.right).toBeLessThanOrEqual(width);
    expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.client + 1);
    await expect(editor.getByRole("button", { name: "Cancel", exact: true })).toBeVisible();
  });
}
