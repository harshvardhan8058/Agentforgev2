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

  test("members administration view has no serious violations", async ({ page }) => {
    await mockCommon(page);
    await seedAuth(page, { role: "owner" });
    const orgId = "11111111-1111-4111-8111-111111111111";
    await mockJson(page, `/orgs/${orgId}/members`, [
      {
        user_id: "22222222-2222-4222-8222-222222222222",
        email: "owner@example.com",
        role: "owner",
        created_at: "2026-07-01T00:00:00Z",
      },
      {
        user_id: "33333333-3333-4333-8333-333333333333",
        email: "member@example.com",
        role: "member",
        created_at: "2026-07-02T00:00:00Z",
      },
    ]);
    await mockJson(page, `/orgs/${orgId}/teams`, [
      { team_id: "44444444-4444-4444-8444-444444444444", name: "Platform", created_at: "2026-07-01T00:00:00Z" },
    ]);
    await mockJson(
      page,
      `/orgs/${orgId}/teams/44444444-4444-4444-8444-444444444444/members`,
      [
        {
          user_id: "33333333-3333-4333-8333-333333333333",
          email: "member@example.com",
          created_at: "2026-07-02T00:00:00Z",
        },
      ],
    );

    await page.goto("/members");
    await expect(page.getByTestId("members-list")).toBeVisible();
    await expect(page.getByTestId("team-members-list")).toBeVisible();
    const results = await scan(page);
    expect(results.violations).toEqual([]);
  });

  test("audit log view has no serious violations", async ({ page }) => {
    await mockCommon(page);
    await seedAuth(page, { role: "owner" });
    await mockJson(page, "/audit-events**", [
      {
        id: "11111111-1111-4111-8111-111111111111",
        action: "member.removed",
        actor_kind: "user",
        actor_id: "22222222-2222-4222-8222-222222222222",
        actor_email: "owner@example.com",
        target_type: "member",
        target_id: "33333333-3333-4333-8333-333333333333",
        metadata: { email: "gone@example.com" },
        created_at: "2026-08-01T10:00:00Z",
      },
    ]);

    await page.goto("/audit");
    await expect(page.getByTestId("audit-table")).toBeVisible();
    const results = await scan(page);
    expect(results.violations).toEqual([]);
  });

  test("webhooks view has no serious violations", async ({ page }) => {
    await mockCommon(page);
    await seedAuth(page, { role: "owner" });
    await mockJson(page, "/webhooks", [
      {
        webhook_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        url: "https://hooks.example.com/agentforge",
        events: ["run.completed", "guardrail.blocked"],
        description: "Ops channel",
        active: true,
        created_at: "2026-08-01T10:00:00Z",
        updated_at: "2026-08-01T10:00:00Z",
      },
    ]);
    await mockJson(page, "/webhooks/*/deliveries**", [
      {
        delivery_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        webhook_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        event: "run.completed",
        status: "failed",
        attempts: 3,
        response_status: 503,
        error: "endpoint refused",
        duration_ms: 1204,
        created_at: "2026-08-01T10:05:00Z",
      },
    ]);

    await page.goto("/webhooks");
    await expect(page.getByTestId("webhooks-list")).toBeVisible();
    // The delivery log is the part with a table, a disclosure button and a live region,
    // so the scan is run with it open rather than only in its collapsed state.
    await page
      .getByTestId("toggle-deliveries-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
      .click();
    await expect(
      page.getByTestId("webhook-delivery-table-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    ).toBeVisible();
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
