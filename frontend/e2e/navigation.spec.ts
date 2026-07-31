import { test, expect } from "@playwright/test";

import { mockCommon, seedAuth } from "./helpers";

/**
 * Navigation + routing: an authenticated owner can reach every primary
 * destination through the sidebar, each view mounts its own surface, and an
 * unknown route renders the in-shell 404.
 */
test.describe("navigation", () => {
  test.beforeEach(async ({ page }) => {
    await mockCommon(page);
    await seedAuth(page, { role: "owner" });
  });

  test("dashboard renders the workspace home for an authenticated owner", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page.getByTestId("home-view")).toBeVisible();
    await expect(page.getByTestId("sidebar")).toBeVisible();
    await expect(page.getByTestId("brand-mark")).toBeVisible();
  });

  test("navigates across primary destinations via the sidebar", async ({ page }) => {
    await page.goto("/");

    const destinations: Array<{ nav: string; view: string }> = [
      { nav: "nav-nav-query", view: "query-view" },
      { nav: "nav-nav-documents", view: "documents-view" },
      { nav: "nav-nav-agent", view: "agent-view" },
      { nav: "nav-nav-multi-agent", view: "multi-agent-view" },
      { nav: "nav-nav-conversations", view: "conversation-view" },
      { nav: "nav-nav-prompts", view: "prompts-view" },
      { nav: "nav-nav-analytics", view: "analytics-view" },
      { nav: "nav-nav-guardrails", view: "guardrails-view" },
      { nav: "nav-nav-evaluations", view: "evaluations-view" },
      { nav: "nav-nav-integrations", view: "integrations-view" },
      { nav: "nav-nav-members", view: "members-view" },
      { nav: "nav-nav-api-keys", view: "api-keys-view" },
      { nav: "nav-nav-audit", view: "audit-view" },
    ];

    for (const { nav, view } of destinations) {
      await page.getByTestId(nav).click();
      await expect(page.getByTestId(view)).toBeVisible();
    }

    // Return home.
    await page.getByTestId("nav-nav-dashboard").click();
    await expect(page.getByTestId("home-view")).toBeVisible();
  });

  test("an unknown route renders the in-shell 404", async ({ page }) => {
    await page.goto("/this-route-does-not-exist");
    await expect(page.getByTestId("not-found-view")).toBeVisible();
    await page.getByTestId("not-found-home").click();
    await expect(page.getByTestId("home-view")).toBeVisible();
  });
});
