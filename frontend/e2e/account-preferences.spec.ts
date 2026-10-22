import { expect, test } from "@playwright/test";

test("profile fields survive session refresh and saved themes control the interface", async ({ page }) => {
  let profile = { id: 1, name: "Owner", email: "owner@example.test", bio: "Saved biography", avatar_url: "", preferences: { theme: "light", language: "es", notifications: { email: false, in_app: false }, future_preference: "retained" } };
  await page.addInitScript(() => localStorage.setItem("chatbot-saas-auth", JSON.stringify({ state: { selectedOrganizationId: "9", activeOrganizationRole: "owner", user: { id: "1", name: "Owner", email: "owner@example.test" } }, version: 0 })));
  await page.route("**/*", async (route) => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname;
    if (!["fetch", "xhr"].includes(request.resourceType()) || path.startsWith("/_next") || url.searchParams.has("_rsc")) return route.continue();
    const respond = (json: unknown) => route.fulfill({ json });
    if (path === "/auth/refresh") return respond({ access_token: "synthetic-session", user: { id: profile.id, name: profile.name, email: profile.email } });
    if (path === "/auth/profile") {
      if (request.method() === "PATCH") profile = { ...profile, ...request.postDataJSON() };
      return respond(profile);
    }
    if (path === "/organizations/") return respond([{ id: 9, name: "Example", role: "owner", slug: "example", created_at: "2026-10-12" }]);
    if (path === "/auth/sessions") return respond([]);
    if (path.endsWith("/usage")) return respond({ usage: {}, limits: {} });
    return route.fulfill({ status: 500, json: { detail: "Unexpected request: " + path } });
  });
  await page.goto("/profile");
  await expect(page.getByLabel("Bio / Tagline", { exact: true })).toHaveValue("Saved biography");
  await page.getByLabel("Bio / Tagline", { exact: true }).fill("Updated biography");
  await page.getByRole("button", { name: "Save Profile", exact: true }).click();
  await expect(page.getByText("Profile saved", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Bio / Tagline", { exact: true })).toHaveValue("Updated biography");
  await page.getByRole("button", { name: "Preferences", exact: true }).click();
  await expect(page.getByLabel("Language", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Notification Preferences", { exact: true })).toHaveCount(0);
  await page.getByLabel("Visual Theme", { exact: true }).selectOption("dark");
  await page.getByRole("button", { name: "Save Preferences", exact: true }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  expect(profile.preferences).toMatchObject({ language: "es", notifications: { email: false, in_app: false }, future_preference: "retained" });
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.getByRole("button", { name: "Preferences", exact: true }).click();
  await page.emulateMedia({ colorScheme: "light" });
  await page.getByLabel("Visual Theme", { exact: true }).selectOption("system");
  await page.getByRole("button", { name: "Save Preferences", exact: true }).click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.getByRole("button", { name: "Switch to light theme", exact: true }).click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
});

for (const sessionRefreshFails of [false, true]) {
  test(`password change clears revoked sessions and ${sessionRefreshFails ? "keeps success when session reload fails" : "shows the rotated session immediately"}`, async ({ page }) => {
    let passwordChanged = false;
    let sessionReadsAfterChange = 0;
    const user = { id: 1, name: "Owner", email: "owner@example.test" };
    const session = (id: number) => ({ id, created_at: "2026-10-22", expires_at: "2026-11-22" });
    await page.addInitScript(() => localStorage.setItem("chatbot-saas-auth", JSON.stringify({ state: { selectedOrganizationId: "9", activeOrganizationRole: "owner", user: { id: "1", name: "Owner", email: "owner@example.test" } }, version: 0 })));
    await page.route("**/*", async (route) => {
      const request = route.request(); const url = new URL(request.url()); const path = url.pathname;
      if (!["fetch", "xhr"].includes(request.resourceType()) || path.startsWith("/_next") || url.searchParams.has("_rsc")) return route.continue();
      const respond = (json: unknown) => route.fulfill({ json });
      if (path === "/auth/refresh") return respond({ access_token: "synthetic-session", user });
      if (path === "/auth/profile") return respond({ ...user, preferences: {} });
      if (path === "/organizations/") return respond([{ id: 9, name: "Example", role: "owner", slug: "example", created_at: "2026-10-12" }]);
      if (path.endsWith("/usage")) return respond({ usage: {}, limits: {} });
      if (path === "/auth/change-password") { passwordChanged = true; return respond({ success: true }); }
      if (path === "/auth/sessions") {
        if (passwordChanged) {
          sessionReadsAfterChange++;
          if (sessionRefreshFails) return route.abort("failed");
        }
        return respond(passwordChanged ? [session(13)] : [session(11), session(12)]);
      }
      return route.fulfill({ status: 500, json: { detail: "Unexpected request: " + path } });
    });
    await page.goto("/profile");
    await page.getByRole("button", { name: "Security & Sessions", exact: true }).click();
    await expect(page.getByText("Device Session (ID: 11)", { exact: true })).toBeVisible();
    await expect(page.getByText("Device Session (ID: 12)", { exact: true })).toBeVisible();
    await page.getByLabel("Current Password", { exact: true }).fill("synthetic-old-password");
    await page.getByLabel("New Password", { exact: true }).fill("synthetic-new-password");
    await page.getByRole("button", { name: "Update Password", exact: true }).click();
    await expect(page.getByText("Password updated", { exact: true })).toBeVisible();
    await expect.poll(() => sessionReadsAfterChange).toBe(1);
    await expect(page.getByText("Device Session (ID: 11)", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Device Session (ID: 12)", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Change failed", { exact: true })).toHaveCount(0);
    if (sessionRefreshFails) await expect(page.getByText("No active sessions loaded.", { exact: true })).toBeVisible();
    else await expect(page.getByText("Device Session (ID: 13)", { exact: true })).toBeVisible();
  });
}
