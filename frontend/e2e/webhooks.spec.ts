import { test, expect } from "@playwright/test";

import { API, mockCommon, mockJson, respond, seedAuth } from "./helpers";

/**
 * Webhooks: the register → store the secret → prove the endpoint works loop, in a real
 * browser.
 *
 * The component tests already cover the states in isolation; what only a browser can check is
 * that the loop an operator actually performs holds together — that the secret survives on
 * screen long enough to be copied, that a test send reports its result, and that a failing
 * consumer is legible in the delivery log rather than looking like a platform error.
 */
const WEBHOOK_ID = "11111111-1111-4111-8111-111111111111";

test.describe("webhooks", () => {
  test.beforeEach(async ({ page }) => {
    await mockCommon(page);
    await seedAuth(page, { role: "owner" });
  });

  test("registers an endpoint and shows the signing secret once", async ({ page }) => {
    let registered = false;
    await page.route(`${API}/webhooks`, (route) => {
      if (route.request().method() === "POST") {
        registered = true;
        return respond(
          route,
          {
            webhook: {
              webhook_id: WEBHOOK_ID,
              url: "https://hooks.example.com/agentforge",
              events: ["run.completed", "run.failed"],
              description: null,
              active: true,
              created_at: "2026-08-01T10:00:00Z",
              updated_at: "2026-08-01T10:00:00Z",
            },
            secret: "whsec-e2e-signing-secret-value",
            secret_note:
              "Store this now: the signing secret is shown once and cannot be retrieved again.",
          },
          201,
        );
      }
      return respond(
        route,
        registered
          ? [
              {
                webhook_id: WEBHOOK_ID,
                url: "https://hooks.example.com/agentforge",
                events: ["run.completed", "run.failed"],
                description: null,
                active: true,
                created_at: "2026-08-01T10:00:00Z",
                updated_at: "2026-08-01T10:00:00Z",
              },
            ]
          : [],
      );
    });

    await page.goto("/webhooks");
    await expect(page.getByTestId("webhooks-view")).toBeVisible();

    await page
      .getByTestId("webhook-url-input")
      .fill("https://hooks.example.com/agentforge");
    await page.getByTestId("webhook-event-run.failed").check();
    await page.getByTestId("create-webhook").click();

    // The secret is a panel, not a toast: it must not vanish on a timer while being copied.
    await expect(page.getByTestId("webhook-secret-panel")).toBeVisible();
    await expect(page.getByTestId("webhook-secret-value")).toHaveText(
      "whsec-e2e-signing-secret-value",
    );

    await expect(page.getByTestId(`webhook-${WEBHOOK_ID}`)).toBeVisible();
    await expect(page.getByTestId(`webhook-state-${WEBHOOK_ID}`)).toHaveText("Active");

    await page.getByTestId("dismiss-webhook-secret").click();
    await expect(page.getByTestId("webhook-secret-panel")).toBeHidden();
  });

  test("reports a successful and then a failing test delivery", async ({ page }) => {
    await mockJson(page, "/webhooks", [
      {
        webhook_id: WEBHOOK_ID,
        url: "https://hooks.example.com/agentforge",
        events: ["run.completed"],
        description: "Ops alerting",
        active: true,
        created_at: "2026-08-01T10:00:00Z",
        updated_at: "2026-08-01T10:00:00Z",
      },
    ]);

    let call = 0;
    await page.route(`${API}/webhooks/*/test`, (route) => {
      call += 1;
      return respond(
        route,
        call === 1
          ? {
              delivery_id: "22222222-2222-4222-8222-222222222222",
              webhook_id: WEBHOOK_ID,
              event: "webhook.ping",
              status: "delivered",
              attempts: 1,
              response_status: 200,
              error: null,
              duration_ms: 91,
              created_at: "2026-08-01T10:01:00Z",
            }
          : {
              delivery_id: "33333333-3333-4333-8333-333333333333",
              webhook_id: WEBHOOK_ID,
              event: "webhook.ping",
              status: "failed",
              attempts: 1,
              response_status: null,
              error: "ConnectTimeout: the endpoint did not answer",
              duration_ms: 4001,
              created_at: "2026-08-01T10:02:00Z",
            },
      );
    });

    await page.goto("/webhooks");
    await page.getByTestId(`test-webhook-${WEBHOOK_ID}`).click();
    // Scoped to the toast list: the same text also appears in the live region that announces
    // it, and matching both is a strict-mode violation rather than a product bug.
    const toasts = page.locator("ol").filter({ hasText: /Test delivery/i });
    await expect(toasts.getByText(/Test delivery succeeded/i)).toBeVisible();

    await page.getByTestId(`test-webhook-${WEBHOOK_ID}`).click();
    // A failing consumer is reported as a result the operator can act on, not as a platform
    // error: the request itself worked.
    await expect(toasts.getByText(/Test delivery failed/i)).toBeVisible();
    await expect(toasts.getByText(/ConnectTimeout/)).toBeVisible();
  });

  test("shows the delivery log and pauses a noisy endpoint", async ({ page }) => {
    let active = true;
    await page.route(`${API}/webhooks`, (route) =>
      respond(route, [
        {
          webhook_id: WEBHOOK_ID,
          url: "https://hooks.example.com/agentforge",
          events: ["run.completed"],
          description: null,
          active,
          created_at: "2026-08-01T10:00:00Z",
          updated_at: "2026-08-01T10:00:00Z",
        },
      ]),
    );
    await page.route(`${API}/webhooks/*`, (route) => {
      if (route.request().method() === "PATCH") {
        active = false;
        return respond(route, {
          webhook_id: WEBHOOK_ID,
          url: "https://hooks.example.com/agentforge",
          events: ["run.completed"],
          description: null,
          active,
          created_at: "2026-08-01T10:00:00Z",
          updated_at: "2026-08-01T10:05:00Z",
        });
      }
      return respond(route, {});
    });
    await mockJson(page, "/webhooks/*/deliveries**", [
      {
        delivery_id: "44444444-4444-4444-8444-444444444444",
        webhook_id: WEBHOOK_ID,
        event: "run.completed",
        status: "failed",
        attempts: 3,
        response_status: 503,
        error: "endpoint returned HTTP 503",
        duration_ms: 12045,
        created_at: "2026-08-01T10:03:00Z",
      },
    ]);

    await page.goto("/webhooks");
    await page.getByTestId(`deliveries-webhook-${WEBHOOK_ID}`).click();

    const table = page.getByTestId(`deliveries-table-${WEBHOOK_ID}`);
    await expect(table).toBeVisible();
    await expect(table.getByText("HTTP 503", { exact: true })).toBeVisible();
    await expect(table.getByText(/endpoint returned HTTP 503/)).toBeVisible();
    // Three attempts, and the endpoint's own time — not the retry backoff.
    await expect(table.getByText("12045 ms")).toBeVisible();

    await page.getByTestId(`toggle-webhook-${WEBHOOK_ID}`).click();
    await expect(page.getByTestId(`webhook-state-${WEBHOOK_ID}`)).toHaveText("Paused");
  });

  test("refuses an inadmissible URL with the server's own message", async ({ page }) => {
    await page.route(`${API}/webhooks`, (route) => {
      if (route.request().method() === "POST") {
        return respond(
          route,
          {
            error: {
              code: "invalid_webhook_url",
              message:
                "the webhook host resolves to an address that is not publicly routable; a webhook URL must not target the deployment's own network",
              details: { field: "url" },
            },
          },
          400,
        );
      }
      return respond(route, []);
    });

    await page.goto("/webhooks");
    await page.getByTestId("webhook-url-input").fill("https://10.0.0.5/hook");
    await page.getByTestId("create-webhook").click();

    await expect(page.getByText(/not publicly routable/i)).toBeVisible();
    await expect(page.getByTestId("webhook-secret-panel")).toBeHidden();
  });

  test("a role without manage_webhooks cannot reach the surface", async ({ page }) => {
    await seedAuth(page, { role: "member" });
    await page.goto("/webhooks");

    await expect(page.getByText(/Webhooks unavailable/i)).toBeVisible();
    await expect(page.getByTestId("register-webhook-card")).toBeHidden();
    // And the destination is absent from the nav, not merely disabled.
    await expect(page.getByTestId("nav-nav-webhooks")).toHaveCount(0);
  });
});
