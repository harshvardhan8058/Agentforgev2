import { test, expect } from "@playwright/test";

import { API, TOKEN_STORAGE_KEY, makeJwt, mockCommon, respond } from "./helpers";

/**
 * Authentication flow: an unauthenticated visitor is gated to /login; a valid
 * credential exchange stores the returned token and lands in the console; a
 * rejected credential keeps the visitor on /login with the envelope message.
 */
test.describe("authentication", () => {
  test("redirects an unauthenticated visitor to /login", async ({ page }) => {
    await mockCommon(page);
    await page.goto("/documents");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByTestId("login-view")).toBeVisible();
  });

  test("logs in with valid credentials and enters the console", async ({ page }) => {
    await mockCommon(page);
    const token = makeJwt({ role: "owner" });
    await page.route(`${API}/auth/login`, (route) =>
      respond(route, { access_token: token, token_type: "bearer" }),
    );

    await page.goto("/login");
    await page.locator("#login-email").fill("owner@example.com");
    await page.locator("#login-password").fill("correct horse battery");
    await page.getByTestId("login-submit").click();

    // Lands on the dashboard and persists the token for the session.
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByTestId("home-view")).toBeVisible();
    const stored = await page.evaluate(
      (key) => localStorage.getItem(key),
      TOKEN_STORAGE_KEY,
    );
    expect(stored).toBe(token);
  });

  test("shows the error envelope and stays on /login for bad credentials", async ({
    page,
  }) => {
    await mockCommon(page);
    await page.route(`${API}/auth/login`, (route) =>
      respond(
        route,
        { error: { code: "auth_failed", message: "Invalid email or password." } },
        401,
      ),
    );

    await page.goto("/login");
    await page.locator("#login-email").fill("owner@example.com");
    await page.locator("#login-password").fill("wrong");
    await page.getByTestId("login-submit").click();

    await expect(page.getByTestId("error-banner")).toContainText(
      "Invalid email or password.",
    );
    await expect(page).toHaveURL(/\/login$/);
  });

  test("blocks submission when fields are empty", async ({ page }) => {
    await mockCommon(page);
    await page.goto("/login");
    await page.getByTestId("login-submit").click();
    await expect(page.getByText("Enter your email to continue.")).toBeVisible();
    await expect(page).toHaveURL(/\/login$/);
  });
});
