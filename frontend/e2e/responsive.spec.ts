import { test, expect, devices } from "@playwright/test";

import { mockCommon, seedAuth } from "./helpers";

/**
 * Responsive shell: on a mobile viewport the persistent sidebar collapses to a
 * drawer opened from the top bar; navigating from the drawer routes and closes
 * it. On desktop the persistent sidebar is present.
 */
test.describe("responsive shell", () => {
  test.beforeEach(async ({ page }) => {
    await mockCommon(page);
    await seedAuth(page, { role: "owner" });
  });

  test.describe("mobile", () => {
    test.use({ viewport: devices["Pixel 7"].viewport });

    test("uses a drawer for navigation on small screens", async ({ page }) => {
      await page.goto("/");
      // The persistent desktop sidebar is not rendered on mobile.
      await expect(page.getByTestId("sidebar")).toHaveCount(0);

      // Open the drawer from the top bar and navigate.
      await page.getByTestId("mobile-nav-trigger").click();
      await expect(page.getByTestId("mobile-drawer")).toBeVisible();
      await page.getByTestId("nav-nav-documents").click();
      await expect(page.getByTestId("documents-view")).toBeVisible();
    });
  });

  test.describe("desktop", () => {
    test.use({ viewport: { width: 1440, height: 900 } });

    test("shows the persistent sidebar on large screens", async ({ page }) => {
      await page.goto("/");
      await expect(page.getByTestId("sidebar")).toBeVisible();
      await expect(page.getByTestId("mobile-nav-trigger")).toHaveCount(0);
    });
  });
});
