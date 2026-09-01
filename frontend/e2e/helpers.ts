import { expect, type Page } from "@playwright/test";

export const e2eEmail = process.env.E2E_EMAIL || "";
export const e2ePassword = process.env.E2E_PASSWORD || "";
export const e2eBotId = process.env.E2E_BOT_ID || "";

export function requireAcceptanceFixture() {
  if (!e2eEmail || !e2ePassword || !e2eBotId) {
    throw new Error("E2E_EMAIL, E2E_PASSWORD, and E2E_BOT_ID are required for Phase I acceptance.");
  }
}

export async function login(page: Page) {
  requireAcceptanceFixture();
  await page.goto("/login");
  await page.getByPlaceholder("Email").fill(e2eEmail);
  await page.getByPlaceholder("Password").fill(e2ePassword);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}
