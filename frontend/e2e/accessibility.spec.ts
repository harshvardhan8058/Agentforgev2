import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

import { mockCommon, mockJson, seedAuth } from "./helpers";

/**
 * Accessibility: full-page axe scans on representative surfaces, asserting no
 * WCAG 2.0/2.1 A/AA violations. Complements the component-level vitest-axe
 * checks with real-browser, full-DOM audits including layout and focus order.
 */
const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

async function scan(page: import("@playwright/test").Page) {
  return new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
}

test.describe("accessibility (axe, WCAG 2.1 AA)", () => {
  test("login page has no serious violations", async ({ page }) => {
    await mockCommon(page);
    await page.goto("/login");
    await expect(page.getByTestId("login-view")).toBeVisible();
    const results = await scan(page);
    expect(results.violations).toEqual([]);
  });

  test("dashboard has no serious violations", async ({ page }) => {
    await mockCommon(page);
    await seedAuth(page, { role: "owner" });
    await page.goto("/");
    await expect(page.getByTestId("home-view")).toBeVisible();
    const results = await scan(page);
    expect(results.violations).toEqual([]);
  });

  test("documents view has no serious violations", async ({ page }) => {
    await mockCommon(page);
    await seedAuth(page, { role: "member" });
    await mockJson(page, "/documents", [
      {
        document_id: "doc-1",
        filename: "policy.pdf",
        content_type: "application/pdf",
        size_bytes: 2048,
        status: "ingested",
        chunk_count: 12,
        created_at: "2024-01-02T03:04:05Z",
      },
    ]);
    await page.goto("/documents");
    await expect(page.getByTestId("document-row-doc-1")).toBeVisible();
    const results = await scan(page);
    expect(results.violations).toEqual([]);
  });

  test("query view has no serious violations", async ({ page }) => {
    await mockCommon(page);
    await seedAuth(page, { role: "member" });
    await page.goto("/query");
    await expect(page.getByTestId("query-view")).toBeVisible();
    const results = await scan(page);
    expect(results.violations).toEqual([]);
  });

  test("the skip link is the first tab stop and moves focus to main", async ({
    page,
  }) => {
    await mockCommon(page);
    await seedAuth(page, { role: "owner" });
    await page.goto("/");
    await expect(page.getByTestId("home-view")).toBeVisible();

    // First Tab reveals and focuses the skip link (WCAG 2.4.1).
    await page.keyboard.press("Tab");
    const skip = page.getByTestId("skip-to-content");
    await expect(skip).toBeFocused();
    await expect(skip).toBeVisible();

    // Activating it moves focus into the main content region.
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("shell-content")).toBeFocused();
  });
});
