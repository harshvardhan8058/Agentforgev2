import { test, expect } from "@playwright/test";

import { mockCommon, mockJson, seedAuth } from "./helpers";

/**
 * Document management: the corpus lists document metadata rows; a zero-document
 * corpus renders the explicit empty state.
 */
test.describe("documents", () => {
  test.beforeEach(async ({ page }) => {
    await mockCommon(page);
    await seedAuth(page, { role: "member" });
  });

  test("lists document metadata rows", async ({ page }) => {
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
    await expect(page.getByTestId("document-filename")).toHaveText("policy.pdf");
    await expect(page.getByTestId("document-status")).toContainText("ingested");
    await expect(page.getByTestId("document-chunk-count")).toHaveText("12");
  });

  test("renders the empty state for a zero-document corpus", async ({ page }) => {
    await mockJson(page, "/documents", []);
    await page.goto("/documents");
    await expect(page.getByTestId("documents-view")).toBeVisible();
    await expect(page.getByTestId("empty-state")).toBeVisible();
  });
});
