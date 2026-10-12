import { expect, test } from "@playwright/test";

for (const view of ["team", "billing", "organization", "analytics"] as const) {
  test(`${view} loads only the data its screen needs`, async ({ page }) => {
    const calls: string[] = [];
    await page.addInitScript(() => localStorage.setItem("chatbot-saas-auth", JSON.stringify({ state: { selectedOrganizationId: "9", activeOrganizationRole: "owner", user: { id: "1", name: "Owner", email: "owner@example.test" } }, version: 0 })));
    await page.route("**/*", async (route) => {
      const request = route.request(); const url = new URL(request.url()); const path = url.pathname;
      if (!["fetch", "xhr"].includes(request.resourceType()) || path.startsWith("/_next") || url.searchParams.has("_rsc")) return route.continue();
      calls.push(path);
      const respond = (json: unknown) => route.fulfill({ json });
      if (path === "/auth/refresh") return respond({ access_token: "synthetic-session", user: { id: 1, name: "Owner", email: "owner@example.test" } });
      if (path === "/organizations/") return respond([{ id: 9, name: "Example", role: "owner", slug: "example", created_at: "2026-10-12" }]);
      if (path.endsWith("/members") || path.endsWith("/invitations")) return respond([]);
      if (path.endsWith("/subscription")) return respond({ plan: { name: "Free" }, status: "active" });
      if (path.endsWith("/details")) return respond(null);
      return route.fulfill({ status: 500, json: { detail: "Unexpected request: " + path } });
    });
    await page.goto(`/${view}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(view[0].toUpperCase() + view.slice(1));
    await expect(page.getByText(/Unexpected request:/)).toHaveCount(0);
    const allowed = ["/auth/refresh", "/organizations/", ...(view === "team" ? ["/organizations/9/members", "/organizations/9/invitations"] : []), ...(view === "billing" ? ["/billing/organizations/9/subscription"] : []), ...(view === "analytics" ? ["/analytics/organization/9/details"] : [])];
    expect(calls.filter((path) => !allowed.includes(path))).toEqual([]);
  });
}
