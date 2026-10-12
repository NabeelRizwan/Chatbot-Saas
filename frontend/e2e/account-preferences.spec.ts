import { expect, test } from "@playwright/test";

test("profile fields survive session refresh and saved themes control the interface", async ({ page }) => {
  let profile = { id: 1, name: "Owner", email: "owner@example.test", bio: "Saved biography", avatar_url: "", preferences: { theme: "light" } };
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
  await page.getByLabel("Visual Theme", { exact: true }).selectOption("dark");
  await page.getByRole("button", { name: "Save Preferences", exact: true }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
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
