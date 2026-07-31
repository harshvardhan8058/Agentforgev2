// @vitest-environment jsdom
import { describe, it, expect, beforeAll, beforeEach, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { axe } from "vitest-axe";
import { toHaveNoViolations } from "vitest-axe/dist/matchers.js";

// vitest-axe ships its type augmentation for an older Vitest `Vi` namespace; declare the
// matcher against Vitest's `Assertion` interface directly.
declare module "vitest" {
  // Must match Vitest's own `Assertion<T = any>` type-parameter signature.
  interface Assertion<T = any> {
    toHaveNoViolations(): T;
  }
  interface AsymmetricMatchersContaining {
    toHaveNoViolations(): void;
  }
}

import { WebhooksView } from "./WebhooksView";
import { ToastProvider } from "../../providers/ToastProvider";
import { SessionContext } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";
import type { Role } from "../../auth/token";

const BASE = "http://localhost:8000";
const server = setupServer();

expect.extend({ toHaveNoViolations });

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// jsdom computes no layout, so contrast is unverifiable here (the Playwright axe lane
// covers it in a real browser).
const AXE_OPTIONS = { rules: { "color-contrast": { enabled: false } } };

const WEBHOOK_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function renderView(role: Role = "owner"): ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SessionContext.Provider value={makeSession(role)}>
        <ToastProvider>
          <WebhooksView />
        </ToastProvider>
      </SessionContext.Provider>
    </QueryClientProvider>,
  );
}

function webhook(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    webhook_id: WEBHOOK_ID,
    url: "https://hooks.example.com/agentforge",
    events: ["run.completed"],
    description: "Ops channel",
    active: true,
    created_at: "2026-07-01T10:00:00Z",
    updated_at: "2026-07-01T10:00:00Z",
    ...overrides,
  };
}

function delivery(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    delivery_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    webhook_id: WEBHOOK_ID,
    event: "run.completed",
    status: "delivered",
    attempts: 1,
    response_status: 200,
    error: null,
    duration_ms: 42,
    created_at: "2026-07-01T10:05:00Z",
    ...overrides,
  };
}

let requests: { method: string; url: URL; body?: unknown }[] = [];

/** Default handlers: one registered webhook and an empty delivery log. */
beforeEach(() => {
  requests = [];
  server.use(
    http.get(`${BASE}/webhooks`, ({ request }) => {
      requests.push({ method: "GET", url: new URL(request.url) });
      return HttpResponse.json([webhook()]);
    }),
    http.get(`${BASE}/webhooks/:id/deliveries`, ({ request }) => {
      requests.push({ method: "GET", url: new URL(request.url) });
      return HttpResponse.json([]);
    }),
  );
});

/**
 * Webhooks: the surface that lets an organization's own systems hear about a run finishing,
 * a document being ingested, or a guardrail refusing an input. Gated on `manage_webhooks`,
 * which is granted from `admin` upwards.
 */
describe("WebhooksView (MSW)", () => {
  it("lists registered endpoints with their events and state", async () => {
    server.use(
      http.get(`${BASE}/webhooks`, () =>
        HttpResponse.json([
          webhook({ webhook_id: "w2", url: "https://b.example.com/h", active: false }),
          webhook({ webhook_id: "w1", events: ["run.failed", "guardrail.blocked"] }),
        ]),
      ),
    );

    renderView("owner");

    await waitFor(() => expect(screen.getByTestId("webhooks-list")).toBeInTheDocument());
    // Order is the server's; the client does not re-sort what it was given.
    expect(screen.getByTestId("webhook-w2")).toHaveTextContent("https://b.example.com/h");
    expect(screen.getByTestId("webhook-w2")).toHaveTextContent("paused");
    expect(screen.getByTestId("webhook-w1")).toHaveTextContent("active");
    expect(screen.getByTestId("webhook-w1")).toHaveTextContent("run.failed");
    expect(screen.getByTestId("webhook-w1")).toHaveTextContent("guardrail.blocked");
  });

  it("offers exactly the events the contract declares subscribable", async () => {
    renderView("owner");
    await waitFor(() => expect(screen.getByTestId("webhooks-list")).toBeInTheDocument());

    for (const event of [
      "run.completed",
      "run.failed",
      "document.ingested",
      "guardrail.blocked",
    ]) {
      expect(screen.getByTestId(`webhook-event-${event}`)).toBeInTheDocument();
    }
    // `webhook.ping` is sent only by the test endpoint, so it must not be offerable.
    expect(screen.queryByTestId("webhook-event-webhook.ping")).toBeNull();
  });

  it("registers a webhook and shows the signing secret once", async () => {
    server.use(
      http.post(`${BASE}/webhooks`, async ({ request }) => {
        const body = await request.json();
        requests.push({ method: "POST", url: new URL(request.url), body });
        return HttpResponse.json(
          { ...webhook({ webhook_id: "new" }), secret: "whsec_supersecret" },
          { status: 201 },
        );
      }),
    );

    renderView("owner");
    await waitFor(() => expect(screen.getByTestId("webhooks-list")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.type(
      screen.getByTestId("webhook-url-input"),
      "https://hooks.example.com/new",
    );
    await user.type(screen.getByTestId("webhook-description-input"), "Alerts");
    await user.click(screen.getByTestId("webhook-event-document.ingested"));
    await user.click(screen.getByTestId("create-webhook"));

    await waitFor(() =>
      expect(screen.getByTestId("created-webhook-secret")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("webhook-secret-value")).toHaveTextContent(
      "whsec_supersecret",
    );
    const post = requests.find((r) => r.method === "POST");
    expect(post?.body).toEqual({
      url: "https://hooks.example.com/new",
      events: ["run.completed", "document.ingested"],
      description: "Alerts",
    });
  });

  it("clears the form after a successful registration so the secret is not re-submitted", async () => {
    server.use(
      http.post(`${BASE}/webhooks`, () =>
        HttpResponse.json({ ...webhook(), secret: "whsec_x" }, { status: 201 }),
      ),
    );

    renderView("owner");
    await waitFor(() => expect(screen.getByTestId("webhooks-list")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.type(screen.getByTestId("webhook-url-input"), "https://a.example.com/h");
    await user.click(screen.getByTestId("create-webhook"));

    await waitFor(() => expect(screen.getByTestId("webhook-url-input")).toHaveValue(""));
  });

  it("will not submit without a URL or without an event", async () => {
    renderView("owner");
    await waitFor(() => expect(screen.getByTestId("webhooks-list")).toBeInTheDocument());

    // No URL yet.
    expect(screen.getByTestId("create-webhook")).toBeDisabled();

    const user = userEvent.setup();
    await user.type(screen.getByTestId("webhook-url-input"), "https://a.example.com/h");
    expect(screen.getByTestId("create-webhook")).toBeEnabled();

    // Unchecking the last event disables it again, with an explanation.
    await user.click(screen.getByTestId("webhook-event-run.completed"));
    expect(screen.getByTestId("create-webhook")).toBeDisabled();
    expect(screen.getByTestId("webhook-events-required")).toBeInTheDocument();
  });

  it("surfaces a refused URL as the server explained it", async () => {
    server.use(
      http.post(`${BASE}/webhooks`, () =>
        HttpResponse.json(
          {
            error: {
              code: "invalid_webhook_url",
              message:
                "a webhook URL must not resolve to a private, loopback, link-local or otherwise internal address",
              details: { field: "url" },
            },
          },
          { status: 400 },
        ),
      ),
    );

    renderView("owner");
    await waitFor(() => expect(screen.getByTestId("webhooks-list")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.type(screen.getByTestId("webhook-url-input"), "https://10.0.0.5/hook");
    await user.click(screen.getByTestId("create-webhook"));

    await waitFor(() =>
      expect(screen.getByTestId("error-message")).toHaveTextContent(
        "must not resolve to a private",
      ),
    );
    expect(screen.queryByTestId("created-webhook-secret")).toBeNull();
  });

  it("pauses and resumes an endpoint", async () => {
    let active = true;
    server.use(
      http.get(`${BASE}/webhooks`, () => HttpResponse.json([webhook({ active })])),
      http.patch(`${BASE}/webhooks/:id`, async ({ request }) => {
        const body = (await request.json()) as { active: boolean };
        requests.push({ method: "PATCH", url: new URL(request.url), body });
        active = body.active;
        return HttpResponse.json(webhook({ active }));
      }),
    );

    renderView("owner");
    await waitFor(() => expect(screen.getByTestId("webhooks-list")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.click(screen.getByTestId(`toggle-active-${WEBHOOK_ID}`));

    await waitFor(() =>
      expect(screen.getByTestId(`webhook-${WEBHOOK_ID}`)).toHaveTextContent("paused"),
    );
    expect(requests.find((r) => r.method === "PATCH")?.body).toEqual({ active: false });
  });

  it("deletes an endpoint after confirmation", async () => {
    let deleted = false;
    server.use(
      http.get(`${BASE}/webhooks`, () =>
        HttpResponse.json(deleted ? [] : [webhook()]),
      ),
      http.delete(`${BASE}/webhooks/:id`, ({ request }) => {
        requests.push({ method: "DELETE", url: new URL(request.url) });
        deleted = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderView("owner");
    await waitFor(() => expect(screen.getByTestId("webhooks-list")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.click(screen.getByTestId(`delete-webhook-${WEBHOOK_ID}`));
    await user.click(screen.getByTestId(`confirm-delete-${WEBHOOK_ID}`));

    await waitFor(() => expect(screen.getByText("No webhooks yet")).toBeInTheDocument());
    expect(requests.some((r) => r.method === "DELETE")).toBe(true);
  });

  it("reports a successful test send", async () => {
    server.use(
      http.post(`${BASE}/webhooks/:id/test`, () =>
        HttpResponse.json(delivery({ event: "webhook.ping" })),
      ),
    );

    renderView("owner");
    await waitFor(() => expect(screen.getByTestId("webhooks-list")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.click(screen.getByTestId(`send-test-${WEBHOOK_ID}`));

    await waitFor(() =>
      expect(screen.getByTestId(`webhook-test-result-${WEBHOOK_ID}`)).toHaveTextContent(
        "delivered 200",
      ),
    );
  });

  it("reports a refused test send as the outcome, not as a broken request", async () => {
    // The API answers 200 with a `failed` delivery: the question was answered, and the
    // consumer's endpoint is what refused. Rendering an app error would blame this API.
    server.use(
      http.post(`${BASE}/webhooks/:id/test`, () =>
        HttpResponse.json(
          delivery({
            event: "webhook.ping",
            status: "failed",
            response_status: 503,
            error: "endpoint refused",
          }),
        ),
      ),
    );

    renderView("owner");
    await waitFor(() => expect(screen.getByTestId("webhooks-list")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.click(screen.getByTestId(`send-test-${WEBHOOK_ID}`));

    await waitFor(() =>
      expect(screen.getByTestId(`webhook-test-result-${WEBHOOK_ID}`)).toHaveTextContent(
        "failed 503",
      ),
    );
    expect(screen.getByTestId(`webhook-test-result-${WEBHOOK_ID}`)).toHaveTextContent(
      "endpoint refused",
    );
    expect(screen.queryByTestId("error-message")).toBeNull();
  });

  it("loads a delivery log only when it is expanded", async () => {
    server.use(
      http.get(`${BASE}/webhooks/:id/deliveries`, ({ request }) => {
        requests.push({ method: "GET", url: new URL(request.url) });
        return HttpResponse.json([
          delivery(),
          delivery({
            delivery_id: "d2",
            status: "failed",
            response_status: 500,
            error: "ConnectTimeout: timed out",
            attempts: 3,
          }),
        ]);
      }),
    );

    renderView("owner");
    await waitFor(() => expect(screen.getByTestId("webhooks-list")).toBeInTheDocument());
    // Closed: the log costs nothing.
    expect(requests.some((r) => r.url.pathname.endsWith("/deliveries"))).toBe(false);

    const user = userEvent.setup();
    await user.click(screen.getByTestId(`toggle-deliveries-${WEBHOOK_ID}`));

    await waitFor(() =>
      expect(screen.getByTestId(`webhook-delivery-table-${WEBHOOK_ID}`)).toBeInTheDocument(),
    );
    expect(screen.getByTestId("webhook-delivery-d2")).toHaveTextContent("failed 500");
    expect(screen.getByTestId("webhook-delivery-d2")).toHaveTextContent("3");
    expect(screen.getByTestId("webhook-delivery-d2")).toHaveTextContent(
      "ConnectTimeout: timed out",
    );
    const deliveriesRequest = requests.find((r) => r.url.pathname.endsWith("/deliveries"));
    expect(deliveriesRequest?.url.searchParams.get("limit")).toBe("25");
  });

  it("says so when an endpoint has never been delivered to", async () => {
    renderView("owner");
    await waitFor(() => expect(screen.getByTestId("webhooks-list")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.click(screen.getByTestId(`toggle-deliveries-${WEBHOOK_ID}`));

    await waitFor(() =>
      expect(
        screen.getByTestId(`webhook-deliveries-empty-${WEBHOOK_ID}`),
      ).toBeInTheDocument(),
    );
  });

  it("shows an empty state before any endpoint is registered", async () => {
    server.use(http.get(`${BASE}/webhooks`, () => HttpResponse.json([])));

    renderView("owner");

    await waitFor(() => expect(screen.getByText("No webhooks yet")).toBeInTheDocument());
  });

  it("surfaces a listing failure with a retry", async () => {
    server.use(
      http.get(`${BASE}/webhooks`, () =>
        HttpResponse.json(
          { error: { code: "internal_error", message: "boom", details: {} } },
          { status: 500 },
        ),
      ),
    );

    renderView("owner");

    await waitFor(() =>
      expect(screen.getByTestId("error-message")).toHaveTextContent("boom"),
    );
    expect(screen.queryByTestId("webhooks-list")).toBeNull();
  });

  it("omits the surface entirely for a role without manage_webhooks", () => {
    // Rendered without any request: a role that cannot manage them must not even ask.
    renderView("member");

    expect(screen.getByTestId("webhooks-view")).toBeInTheDocument();
    expect(screen.getByText("Webhook management unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("webhooks-list")).toBeNull();
    expect(screen.queryByTestId("create-webhook")).toBeNull();
    expect(requests).toEqual([]);
  });

  it("is reachable by an admin: webhook config discloses no credential", async () => {
    renderView("admin");

    await waitFor(() => expect(screen.getByTestId("webhooks-list")).toBeInTheDocument());
    expect(screen.getByTestId("create-webhook")).toBeInTheDocument();
  });

  it("announces the endpoint count for a screen reader", async () => {
    renderView("owner");

    await waitFor(() =>
      expect(screen.getByTestId("webhooks-status")).toHaveTextContent(
        "1 webhook registered",
      ),
    );
  });

  it("has no axe violations with endpoints and an open delivery log", async () => {
    server.use(
      http.get(`${BASE}/webhooks/:id/deliveries`, () => HttpResponse.json([delivery()])),
    );
    const { container } = renderView("owner");
    await waitFor(() => expect(screen.getByTestId("webhooks-list")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.click(screen.getByTestId(`toggle-deliveries-${WEBHOOK_ID}`));
    await waitFor(() =>
      expect(screen.getByTestId(`webhook-delivery-table-${WEBHOOK_ID}`)).toBeInTheDocument(),
    );

    const results = await axe(container, AXE_OPTIONS);
    expect(results).toHaveNoViolations();
  });

  it("marks the delivery toggle's expanded state for assistive technology", async () => {
    renderView("owner");
    await waitFor(() => expect(screen.getByTestId("webhooks-list")).toBeInTheDocument());

    const toggle = screen.getByTestId(`toggle-deliveries-${WEBHOOK_ID}`);
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    const user = userEvent.setup();
    await user.click(toggle);

    await waitFor(() => expect(toggle).toHaveAttribute("aria-expanded", "true"));
  });
});
