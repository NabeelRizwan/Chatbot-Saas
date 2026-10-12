import { expect, test, type Page } from "@playwright/test";

async function isolate(page: Page, signedIn = false) {
  const requests: string[] = [];
  await page.route("**/*", async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    if (!["fetch", "xhr"].includes(request.resourceType()) || path.startsWith("/_next") || new URL(request.url()).searchParams.has("_rsc")) return route.continue();
    requests.push(path);
    const json = (data: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (path === "/auth/refresh") return signedIn ? json({ access_token: "synthetic-local-session", user: { id: 1, name: "Test user", email: "user@example.test", is_admin: false } }) : json({ detail: "No signed-in session" }, 401);
    if (path === "/organizations/") return json([{ id: 9, name: "Example workspace", slug: "example", role: "viewer", created_at: "2026-10-12" }]);
    return json({ detail: "Outside isolated homepage test" }, 503);
  });
  return requests;
}

test("anonymous homepage has working preview, anchors and signup route", async ({ page }) => {
  const calls = await isolate(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Let it talk.");
  await page.getByRole("button", { name: "Contact requests", exact: true }).click();
  await expect(page.getByText("Can someone help with my project?", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Take a closer look", exact: true }).click();
  await expect(page).toHaveURL(/#experience$/);
  await page.getByRole("link", { name: "Build your chatbot", exact: true }).first().click();
  await expect(page).toHaveURL(/\/signup$/);
  await expect(page.getByRole("heading", { name: "Create workspace", exact: true })).toBeVisible();
  expect(calls.every((path) => path === "/auth/refresh")).toBe(true);
});

test("existing signed-in user keeps the dashboard at the original root route", async ({ page }) => {
  await isolate(page, true);
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Dashboard", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Bots", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Your website/ })).toHaveCount(0);
  await expect(page).toHaveURL(/\/$/);
});

test("homepage menu, FAQ and skip link work with keyboard on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await isolate(page);
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content", exact: true })).toBeFocused();
  await page.getByRole("button", { name: "Open menu", exact: true }).click();
  await expect(page.getByRole("navigation", { name: "Mobile navigation" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("navigation", { name: "Mobile navigation" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Open menu", exact: true })).toBeFocused();
  const question = page.locator("summary").filter({ hasText: "Can I use it without a website?" });
  await question.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText(/Enable customer experience features and the standalone chat link/)).toBeVisible();
  const size = await page.evaluate(() => ({ width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
  expect(size.scroll).toBeLessThanOrEqual(size.width + 1);
});

test("homepage desktop and mobile visual evidence", async ({ page }, testInfo) => {
  await isolate(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("landing-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: testInfo.outputPath("landing-mobile.png"), fullPage: true });
});

test("sign-in fields have labels and Enter submits through the existing auth API", async ({ page }) => {
  await isolate(page);
  let submitted: unknown = null;
  await page.route("**/auth/login", (route) => {
    submitted = route.request().postDataJSON();
    return route.fulfill({ json: { access_token: "synthetic-local-session", expires_in: 3600, user: { id: 1, name: "Test user", email: "user@example.test", is_admin: false } } });
  });
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill("user@example.test");
  await page.getByLabel("Password", { exact: true }).fill("Synthetic-Local-Test-Only!");
  await page.getByLabel("Password", { exact: true }).press("Enter");
  await expect(page.getByRole("link", { name: "Dashboard", exact: true })).toBeVisible();
  expect(submitted).toEqual({ email: "user@example.test", password: "Synthetic-Local-Test-Only!" });
});

test("welcome page remains publicly viewable without changing an existing session", async ({ page }) => {
  const calls = await isolate(page, true);
  await page.goto("/welcome");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Let it talk.");
  await expect(page.getByRole("link", { name: "Sign in", exact: true }).first()).toBeVisible();
  expect(calls).toEqual([]);
});
