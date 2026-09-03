import { expect, test, type Page } from "@playwright/test";

// Real rendered Next/React UI, deterministic intercepted API. No accounts,
// credentials, provider calls, or customer database changes are made.
const providerOptions = { providers: [
  { id: "gemini", models: ["gemini-2.5-flash", "gemini-1.5-pro"] },
  { id: "openai", models: ["gpt-4.1-mini", "gpt-4.1"] },
  { id: "claude", models: ["claude-3-5-sonnet"] },
  { id: "grok", models: ["grok-2"] },
], allocation_mode: "one_bot_per_profile" };
const profile = (id: number, provider = "gemini", status = "available", botId: number | null = null) => ({
  id, credential_profile_id: id, provider, label: `${provider} profile ${id}`, status,
  allocated_to_bot_id: botId, assigned_bot_count: botId === null ? 0 : 1, bot: null,
  created_at: "2026-09-01T00:00:00", updated_at: "2026-09-01T00:00:00",
  // Deliberately injected to prove the renderer only displays safe fields.
  api_key: "synthetic-should-not-render", encrypted_key: "synthetic-ciphertext-should-not-render",
});
const initialBot = { id: 7, name: "Example bot", organization_id: 9, organization_name: "Example organization", customer_name: "Example customer", status: "active", provider: "gemini", model_name: "gemini-2.5-flash", usage_mode: "platform", credential_profile_id: null, credential_label: null, credential_status: null };

async function mockApi(page: Page, admin = true) {
  const calls: { method: string; path: string; body: Record<string, unknown> | null }[] = [];
  let keys = [profile(1), profile(2, "openai"), profile(3, "gemini", "disabled"), profile(4, "gemini", "assigned", 99)];
  let bot: Record<string, unknown> = { ...initialBot };
  await page.route("**/*", async (route) => {
    const req = route.request(); const url = new URL(req.url()); const path = url.pathname;
    if (!["fetch", "xhr"].includes(req.resourceType()) || path.startsWith("/_next") || url.searchParams.has("_rsc")) return route.continue();
    const method = req.method();
    const body = req.postData() ? req.postDataJSON() as Record<string, unknown> : null;
    calls.push({ method, path, body });
    const respond = (data: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (path === "/auth/refresh") return respond({ access_token: "synthetic-access", user: { id: 1, name: "Operator", email: "operator@example.test", is_admin: admin } });
    if (path === "/admin/session") return respond(admin ? { user_id: 1, is_admin: true } : { detail: "Platform administrator privileges required." }, admin ? 200 : 403);
    if (path === "/admin/provider-options") return respond(providerOptions);
    if (path === "/admin/overview") return respond({ organizations: 2, bots: 3, enabled_credentials: 4 });
    if (path === "/admin/organizations") return respond({ items: [{ id: 9, name: "Example organization", bot_count: 1, created_at: "2026-09-01" }], total: 1, offset: 0, limit: 25 });
    if (path === "/admin/bots") return respond({ items: [bot], total: 1, offset: 0, limit: 25 });
    if (path.endsWith("/provider-config")) { bot = { ...bot, ...body }; return respond(bot); }
    if (path === "/admin/platform-keys" && method === "GET") return respond({ items: keys, total: keys.length, offset: 0, limit: 25 });
    if (path === "/admin/platform-keys" && method === "POST") {
      const added = { ...profile(10, String(body?.provider)), label: String(body?.label) };
      keys = [...keys, added]; return respond(added, 201);
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
  await page.getByLabel("Label", { exact: true }).fill("Secondary profile");
  await page.getByLabel("API secret", { exact: true }).fill("synthetic-new-secret-only");
  await page.getByRole("button", { name: "Save credential", exact: true }).click();
  await expect(page.getByLabel("API secret", { exact: true })).toHaveValue("");
  await expect(page.getByRole("status")).toContainText("Credential saved");
  expect(calls.find((call) => call.path === "/admin/platform-keys" && call.method === "POST")?.body?.api_key).toBe("synthetic-new-secret-only");
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

test("bot selector filters provider, disabled and other-bot profiles; saves a snapshot", async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto("/admin/bots");
  await page.getByRole("button", { name: "Configure", exact: true }).click();
  const selector = page.getByRole("combobox", { name: "Credential profile", exact: true });
  await expect(selector).toContainText("gemini profile 1");
  await expect(selector).not.toContainText("openai profile 2");
  await expect(selector).not.toContainText("gemini profile 3");
  await expect(selector).not.toContainText("gemini profile 4");
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
