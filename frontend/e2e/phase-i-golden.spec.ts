import { expect, test } from "@playwright/test";

import { e2eBotId, login, requireAcceptanceFixture } from "./helpers";


test.beforeAll(() => requireAcceptanceFixture());

test("login, refresh, bot read-back, knowledge, and dashboard routes remain usable", async ({ page }) => {
  await login(page);
  await page.reload();
  await expect(page.getByText("Phase I Workspace").first()).toBeVisible();

  await page.goto(`/bots/${e2eBotId}?tab=general`);
  await expect(page.getByRole("heading", { name: "Phase I Atlas Assistant" }).first()).toBeVisible();
  await expect(page.getByPlaceholder("Customer Support Assistant")).toHaveValue("Phase I Atlas Assistant");
  await expect(page.getByLabel("Category")).toHaveValue("sales");

  await page.getByRole("button", { name: "Knowledge Base" }).click();
  await expect(page.getByRole("heading", { name: "Web Scraping Sandbox" })).toBeVisible();
  await expect(page.getByText("11 chunks/1,039 tokens")).toBeVisible();

  for (const route of ["/bots", "/knowledge", "/conversations", "/analytics", "/team", "/billing", "/settings"]) {
    await page.goto(route);
    await expect(page).not.toHaveURL(/\/login/);
    await expect(page.getByText(/404|page not found/i)).toHaveCount(0);
  }
});

test("core dashboard and bot editor remain usable at a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await page.goto(`/bots/${e2eBotId}?tab=knowledge`);
  await expect(page.getByRole("heading", { name: "Phase I Atlas Assistant" }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Chat playground" })).toBeVisible();
});

test("two external widget visitors receive distinct sessions and grounded sources", async ({ browser }) => {
  test.skip(process.env.PHASE_I_LIVE_EXTERNAL !== "1", "Set PHASE_I_LIVE_EXTERNAL=1 for live widget acceptance.");
  const originA = process.env.E2E_EXTERNAL_ORIGIN_A || "http://127.0.0.1:4173";
  const originB = process.env.E2E_EXTERNAL_ORIGIN_B || "http://127.0.0.1:4174";
  const contextA = await browser.newContext();
  const contextB = await browser.newContext();
  const visitorA = await contextA.newPage();
  const visitorB = await contextB.newPage();

  try {
    await Promise.all([
      visitorA.goto(`${originA}/?botId=${e2eBotId}`),
      visitorB.goto(`${originB}/?botId=${e2eBotId}`),
    ]);
    await Promise.all([
      expect(visitorA.getByRole("button", { name: "Atlas help" })).toBeVisible(),
      expect(visitorB.getByRole("button", { name: "Atlas help" })).toBeVisible(),
    ]);

    for (const visitor of [visitorA, visitorB]) {
      const input = visitor.getByRole("textbox", { name: "Type your message..." });
      await input.fill("Which sports statistics can I explore?");
      await input.press("Enter");
      await expect(visitor.getByText(/NHL team stat/i)).toBeVisible({ timeout: 75_000 });
      await expect(visitor.getByRole("link", { name: "Web Scraping Sandbox" })).toHaveAttribute("href", /^https:\/\//);
    }

    const sessionA = await visitorA.evaluate((botId) => sessionStorage.getItem(`chatbot-widget-credential-${botId}`), e2eBotId);
    const sessionB = await visitorB.evaluate((botId) => sessionStorage.getItem(`chatbot-widget-credential-${botId}`), e2eBotId);
    expect(sessionA).toBeTruthy();
    expect(sessionB).toBeTruthy();
    expect(JSON.parse(sessionA as string).session_id).not.toBe(JSON.parse(sessionB as string).session_id);
  } finally {
    await contextA.close();
    await contextB.close();
  }
});
