import { test, expect } from "@playwright/test";

import { API, mockCommon, mockJson, respond, seedAuth } from "./helpers";

/**
 * Webhooks: the administrative surface for outbound event delivery.
 *
 * Driven in a real browser because the two interactions that matter most are browser
 * behaviours rather than render output: the one-time secret disclosure (which must survive a
 * form reset and be selectable/copyable), and the disclosure panel that fetches a delivery log
 * only once opened. The MSW component tests assert the wiring; this asserts the flow.
 */
const WEBHOOK_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function subscription(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    webhook_id: WEBHOOK_ID,
    url: "https://hooks.example.com/agentforge",
    events: ["run.completed"],
    description: "Ops channel",
    active: true,
    created_at: "2026-08-01T10:00:00Z",
    updated_at: "2026-08-01T10:00:00Z",
    ...overrides,
  };
}

test.describe("webhooks", () => {
  test.beforeEach(async ({ page }) => {
    await mockCommon(page);
    await seedAuth(page, { role: "owner" });
  });

  test("registers an endpoint and discloses the signing secret once", async ({ page }) => {
    let created = false;
    await page.route(`${API}/webhooks`, (route) => {
      if (route.request().method() === "POST") {
        created = true;
        return respond(
          route,
          { ...subscription(), secret: "whsec_shown_once_only" },
          201,
        );
      }
      return respond(route, created ? [subscription()] : []);
    });

    await page.goto("/webhooks");
    await expect(page.getByTestId("webhooks-view")).toBeVisible();

    await page.getByTestId("webhook-url-input").fill("https://hooks.example.com/agentforge");
    await page.getByTestId("webhook-description-input").fill("Ops channel");
    await page.getByTestId("webhook-event-guardrail.blocked").check();
    await page.getByTestId("create-webhook").click();

    await expect(page.getByTestId("webhook-secret-value")).toHaveText(
      "whsec_shown_once_only",
    );
    // The endpoint now appears in the list, and the form is cleared so the next
    // registration cannot accidentally re-submit the previous URL.
    await expect(page.getByTestId(`webhook-${WEBHOOK_ID}`)).toBeVisible();
    await expect(page.getByTestId("webhook-url-input")).toHaveValue("");
  });

  test("refuses an internal URL with the server's explanation", async ({ page }) => {
    await page.route(`${API}/webhooks`, (route) => {
      if (route.request().method() === "POST") {
        return respond(
          route,
          {
            error: {
              code: "invalid_webhook_url",
              message:
                "a webhook URL must not resolve to a private, loopback, link-local or otherwise internal address",
              details: { field: "url" },
            },
          },
          400,
        );
      }
      return respond(route, []);
    });

    await page.goto("/webhooks");
    await page.getByTestId("webhook-url-input").fill("https://169.254.169.254/latest/meta-data/");
    await page.getByTestId("create-webhook").click();

    await expect(page.getByTestId("error-message")).toContainText(
      "must not resolve to a private",
    );
    await expect(page.getByTestId("webhook-secret-value")).toHaveCount(0);
  });

  test("sends a test delivery and reports a refusal as the outcome", async ({ page }) => {
    await mockJson(page, "/webhooks", [subscription()]);
    await mockJson(page, `/webhooks/*/test`, {
      delivery_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
      webhook_id: WEBHOOK_ID,
      event: "webhook.ping",
      status: "failed",
      attempts: 1,
      response_status: 503,
      error: "endpoint refused",
      duration_ms: 88,
      created_at: "2026-08-01T10:05:00Z",
    });

    await page.goto("/webhooks");
    await page.getByTestId(`send-test-${WEBHOOK_ID}`).click();

    // A refused endpoint is a successful answer to the question the operator asked, so the
    // status code and diagnostic are shown rather than an application error.
    await expect(page.getByTestId(`webhook-test-result-${WEBHOOK_ID}`)).toContainText(
      "failed 503",
    );
    await expect(page.getByTestId(`webhook-test-result-${WEBHOOK_ID}`)).toContainText(
      "endpoint refused",
    );
  });

  test("loads the delivery log only when the panel is opened", async ({ page }) => {
    await mockJson(page, "/webhooks", [subscription()]);
    let deliveryRequests = 0;
    await page.route(`${API}/webhooks/*/deliveries**`, (route) => {
      if (route.request().method() !== "OPTIONS") deliveryRequests += 1;
      return respond(route, [
        {
          delivery_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
          webhook_id: WEBHOOK_ID,
          event: "run.completed",
          status: "delivered",
          attempts: 2,
          response_status: 200,
          error: null,
          duration_ms: 315,
          created_at: "2026-08-01T10:05:00Z",
        },
      ]);
    });

    await page.goto("/webhooks");
    await expect(page.getByTestId(`webhook-${WEBHOOK_ID}`)).toBeVisible();
    expect(deliveryRequests).toBe(0);

    await page.getByTestId(`toggle-deliveries-${WEBHOOK_ID}`).click();

    await expect(
      page.getByTestId(`webhook-delivery-table-${WEBHOOK_ID}`),
    ).toBeVisible();
    // `attempts` > 1 with `delivered` is what tells an operator the endpoint is flaky.
    await expect(
      page.getByTestId("webhook-delivery-dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
    ).toContainText("delivered 200");
    expect(deliveryRequests).toBe(1);
  });

  test("pauses an endpoint without losing it", async ({ page }) => {
    let active = true;
    await page.route(`${API}/webhooks`, (route) =>
      respond(route, [subscription({ active })]),
    );
    await page.route(`${API}/webhooks/${WEBHOOK_ID}`, async (route) => {
      if (route.request().method() === "PATCH") {
        active = false;
        return respond(route, subscription({ active: false }));
      }
      return respond(route, {});
    });

    await page.goto("/webhooks");
    await expect(page.getByTestId(`webhook-${WEBHOOK_ID}`)).toContainText("active");

    await page.getByTestId(`toggle-active-${WEBHOOK_ID}`).click();

    // Paused, not deleted: the endpoint and its history stay, so resuming needs no re-keying.
    await expect(page.getByTestId(`webhook-${WEBHOOK_ID}`)).toContainText("paused");
    await expect(page.getByTestId(`toggle-active-${WEBHOOK_ID}`)).toContainText("Resume");
  });

  test("hides the surface from a role without manage_webhooks", async ({ page }) => {
    await seedAuth(page, { role: "member" });

    await page.goto("/webhooks");

    await expect(page.getByTestId("webhooks-view")).toBeVisible();
    await expect(page.getByText("Webhook management unavailable")).toBeVisible();
    // Not merely disabled — absent from the DOM.
    await expect(page.getByTestId("create-webhook")).toHaveCount(0);
    await expect(page.getByTestId("nav-nav-webhooks")).toHaveCount(0);
  });
});
