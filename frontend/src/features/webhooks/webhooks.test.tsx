// @vitest-environment jsdom
import { describe, it, expect, beforeAll, beforeEach, afterAll, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
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
import { SessionContext } from "../../auth/useSession";
import { ToastProvider } from "../../providers/ToastProvider";
import { makeSession } from "../../test/renderWithSession";
import type { Role } from "../../auth/token";

const BASE = "http://localhost:8000";
const server = setupServer();

expect.extend({ toHaveNoViolations });

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// jsdom computes no layout, so contrast is unverifiable here (the Playwright axe lane covers
// it in a real browser).
const AXE_OPTIONS = { rules: { "color-contrast": { enabled: false } } };

const WEBHOOK_ID = "11111111-1111-4111-8111-111111111111";

function renderView(role: Role = "owner"): ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <SessionContext.Provider value={makeSession(role)}>
          <WebhooksView />
        </SessionContext.Provider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function webhook(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    webhook_id: WEBHOOK_ID,
    url: "https://hooks.example.com/agentforge",
    events: ["run.completed"],
    description: "Ops alerting",
    active: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

function delivery(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    delivery_id: "22222222-2222-4222-8222-222222222222",
    webhook_id: WEBHOOK_ID,
    event: "run.completed",
    status: "delivered",
    attempts: 1,
    response_status: 200,
    error: null,
    duration_ms: 84,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

/** Bodies the view sent, so mutation wiring can be asserted. */
let posted: unknown[] = [];

beforeEach(() => {
  posted = [];
  server.use(
    http.get(`${BASE}/webhooks`, () => HttpResponse.json([])),
    http.get(`${BASE}/webhooks/:id/deliveries`, () => HttpResponse.json([])),
    // The queue panel is part of the page now; its own behaviour is covered in queue.test.tsx.
    http.get(`${BASE}/webhooks/queue`, () =>
      HttpResponse.json({ pending: 0, abandoned: 0, entries: [] }),
    ),
  );
});

/**
 * The webhooks console: register an endpoint, prove it works, watch what was delivered.
 * Gated on `manage_webhooks`, which is granted from `admin` upwards.
 */
describe("WebhooksView (MSW)", () => {
  it("shows an empty state when nothing is registered", async () => {
    renderView();
    expect(await screen.findByText(/No webhooks registered/i)).toBeInTheDocument();
  });

  it("renders a skeleton while loading", async () => {
    server.use(
      http.get(`${BASE}/webhooks`, async () => {
        await new Promise((resolve) => setTimeout(resolve, 30));
        return HttpResponse.json([webhook()]);
      }),
    );
    renderView();
    expect(screen.getByTestId("webhooks-skeleton")).toBeInTheDocument();
    expect(await screen.findByTestId(`webhook-${WEBHOOK_ID}`)).toBeInTheDocument();
  });

  it("lists a subscription with its state and events", async () => {
    server.use(http.get(`${BASE}/webhooks`, () => HttpResponse.json([webhook()])));
    renderView();

    const row = await screen.findByTestId(`webhook-${WEBHOOK_ID}`);
    expect(within(row).getByText("https://hooks.example.com/agentforge")).toBeInTheDocument();
    expect(within(row).getByText("Ops alerting")).toBeInTheDocument();
    expect(screen.getByTestId(`webhook-state-${WEBHOOK_ID}`)).toHaveTextContent("Active");
    expect(within(row).getByText("run.completed")).toBeInTheDocument();
  });

  it("renders a paused subscription as paused", async () => {
    server.use(
      http.get(`${BASE}/webhooks`, () => HttpResponse.json([webhook({ active: false })])),
    );
    renderView();
    expect(await screen.findByTestId(`webhook-state-${WEBHOOK_ID}`)).toHaveTextContent(
      "Paused",
    );
  });

  it("offers exactly the events the contract declares as subscribable", async () => {
    renderView();
    await screen.findByTestId("webhook-event-checklist");
    // Generated from `Subscribable_Event`, so `webhook.ping` (which nothing emits) is absent.
    for (const event of [
      "run.completed",
      "run.failed",
      "document.ingested",
      "guardrail.blocked",
      "budget.threshold_crossed",
    ]) {
      expect(screen.getByTestId(`webhook-event-${event}`)).toBeInTheDocument();
    }
    expect(screen.queryByTestId("webhook-event-webhook.ping")).not.toBeInTheDocument();
  });

  it("registers a webhook and shows the secret exactly once", async () => {
    server.use(
      http.post(`${BASE}/webhooks`, async ({ request }) => {
        posted.push(await request.json());
        return HttpResponse.json(
          {
            webhook: webhook(),
            secret: "super-secret-signing-key",
            secret_note:
              "Store this now: the signing secret is shown once and cannot be retrieved again.",
          },
          { status: 201 },
        );
      }),
    );
    renderView();
    const user = userEvent.setup();

    await user.type(
      await screen.findByTestId("webhook-url-input"),
      "https://hooks.example.com/agentforge",
    );
    await user.click(screen.getByTestId("webhook-event-guardrail.blocked"));
    await user.click(screen.getByTestId("create-webhook"));

    const panel = await screen.findByTestId("webhook-secret-panel");
    expect(within(panel).getByText(/shown once/i)).toBeInTheDocument();
    expect(screen.getByTestId("webhook-secret-value")).toHaveTextContent(
      "super-secret-signing-key",
    );
    expect(posted).toEqual([
      {
        url: "https://hooks.example.com/agentforge",
        events: ["run.completed", "guardrail.blocked"],
        active: true,
      },
    ]);
  });

  it("lets the operator dismiss the secret panel once it is stored", async () => {
    server.use(
      http.post(`${BASE}/webhooks`, () =>
        HttpResponse.json(
          {
            webhook: webhook(),
            secret: "super-secret-signing-key",
            secret_note:
              "Store this now: the signing secret is shown once and cannot be retrieved again.",
          },
          { status: 201 },
        ),
      ),
    );
    renderView();
    const user = userEvent.setup();

    await user.type(await screen.findByTestId("webhook-url-input"), "https://h.example/x");
    await user.click(screen.getByTestId("create-webhook"));
    await screen.findByTestId("webhook-secret-panel");

    await user.click(screen.getByTestId("dismiss-webhook-secret"));
    expect(screen.queryByTestId("webhook-secret-panel")).not.toBeInTheDocument();
  });

  it("cannot be submitted without a URL or without an event", async () => {
    renderView();
    const user = userEvent.setup();

    expect(await screen.findByTestId("create-webhook")).toBeDisabled();

    await user.type(screen.getByTestId("webhook-url-input"), "https://h.example/x");
    expect(screen.getByTestId("create-webhook")).toBeEnabled();

    // Unchecking the only selected event disables it again and says why.
    await user.click(screen.getByTestId("webhook-event-run.completed"));
    expect(screen.getByTestId("create-webhook")).toBeDisabled();
    expect(screen.getByTestId("webhook-no-events-hint")).toBeInTheDocument();
  });

  it("surfaces the server's URL refusal verbatim rather than re-implementing the rules", async () => {
    server.use(
      http.post(`${BASE}/webhooks`, () =>
        HttpResponse.json(
          {
            error: {
              code: "invalid_webhook_url",
              message:
                "the webhook host resolves to an address that is not publicly routable",
              details: { field: "url" },
            },
          },
          { status: 400 },
        ),
      ),
    );
    renderView();
    const user = userEvent.setup();

    await user.type(await screen.findByTestId("webhook-url-input"), "https://10.0.0.5/h");
    await user.click(screen.getByTestId("create-webhook"));

    expect(
      await screen.findByText(/not publicly routable/i),
    ).toBeInTheDocument();
  });

  it("pauses and resumes a subscription", async () => {
    let active = true;
    server.use(
      http.get(`${BASE}/webhooks`, () => HttpResponse.json([webhook({ active })])),
      http.patch(`${BASE}/webhooks/:id`, async ({ request }) => {
        const body = (await request.json()) as { active?: boolean };
        posted.push(body);
        active = body.active ?? active;
        return HttpResponse.json(webhook({ active }));
      }),
    );
    renderView();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId(`toggle-webhook-${WEBHOOK_ID}`));

    expect(posted).toEqual([{ active: false }]);
    await waitFor(() =>
      expect(screen.getByTestId(`webhook-state-${WEBHOOK_ID}`)).toHaveTextContent("Paused"),
    );
  });

  it("sends a test delivery and reports a success", async () => {
    server.use(
      http.get(`${BASE}/webhooks`, () => HttpResponse.json([webhook()])),
      http.post(`${BASE}/webhooks/:id/test`, () =>
        HttpResponse.json(delivery({ event: "webhook.ping" })),
      ),
    );
    renderView();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId(`test-webhook-${WEBHOOK_ID}`));

    expect(await screen.findByText(/Test delivery succeeded/i)).toBeInTheDocument();
  });

  it("reports a failed test delivery as a result, not as an error banner", async () => {
    server.use(
      http.get(`${BASE}/webhooks`, () => HttpResponse.json([webhook()])),
      http.post(`${BASE}/webhooks/:id/test`, () =>
        HttpResponse.json(
          delivery({
            event: "webhook.ping",
            status: "failed",
            response_status: null,
            error: "ConnectTimeout: endpoint did not answer",
          }),
        ),
      ),
    );
    renderView();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId(`test-webhook-${WEBHOOK_ID}`));

    expect(await screen.findByText(/Test delivery failed/i)).toBeInTheDocument();
    expect(await screen.findByText(/ConnectTimeout/)).toBeInTheDocument();
  });

  it("shows the delivery log with its result and endpoint time", async () => {
    server.use(
      http.get(`${BASE}/webhooks`, () => HttpResponse.json([webhook()])),
      http.get(`${BASE}/webhooks/:id/deliveries`, () =>
        HttpResponse.json([
          delivery(),
          delivery({
            delivery_id: "33333333-3333-4333-8333-333333333333",
            status: "failed",
            response_status: 500,
            error: "endpoint returned HTTP 500",
            attempts: 3,
            duration_ms: 4012,
          }),
        ]),
      ),
    );
    renderView();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId(`deliveries-webhook-${WEBHOOK_ID}`));

    const table = await screen.findByTestId(`deliveries-table-${WEBHOOK_ID}`);
    expect(within(table).getByText("HTTP 200")).toBeInTheDocument();
    expect(within(table).getByText("HTTP 500")).toBeInTheDocument();
    expect(within(table).getByText(/endpoint returned HTTP 500/)).toBeInTheDocument();
    // The endpoint's own time, excluding the backoff between the three attempts.
    expect(within(table).getByText("84 ms")).toBeInTheDocument();
    expect(within(table).getByText("4012 ms")).toBeInTheDocument();
  });

  it("says so when a subscription has no deliveries yet", async () => {
    server.use(http.get(`${BASE}/webhooks`, () => HttpResponse.json([webhook()])));
    renderView();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId(`deliveries-webhook-${WEBHOOK_ID}`));

    expect(
      await screen.findByTestId(`deliveries-empty-${WEBHOOK_ID}`),
    ).toBeInTheDocument();
  });

  it("pages older deliveries with the server's keyset cursor", async () => {
    const firstPage = Array.from({ length: 25 }, (_unused, index) =>
      delivery({
        delivery_id: `44444444-4444-4444-8444-4444444444${String(index).padStart(2, "0")}`,
        created_at: new Date(Date.now() - index * 1000).toISOString(),
      }),
    );
    const cursors: URL[] = [];
    server.use(
      http.get(`${BASE}/webhooks`, () => HttpResponse.json([webhook()])),
      http.get(`${BASE}/webhooks/:id/deliveries`, ({ request }) => {
        const url = new URL(request.url);
        cursors.push(url);
        if (url.searchParams.has("before")) {
          return HttpResponse.json([
            delivery({ delivery_id: "55555555-5555-4555-8555-555555555555" }),
          ]);
        }
        return HttpResponse.json(firstPage);
      }),
    );
    renderView();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId(`deliveries-webhook-${WEBHOOK_ID}`));
    await screen.findByTestId(`deliveries-table-${WEBHOOK_ID}`);

    await user.click(screen.getByTestId(`load-older-deliveries-${WEBHOOK_ID}`));

    await waitFor(() =>
      expect(
        screen.getByTestId("delivery-55555555-5555-4555-8555-555555555555"),
      ).toBeInTheDocument(),
    );
    // Both halves of the cursor, which is what makes a page boundary safe when several
    // deliveries share a timestamp.
    const paged = cursors.at(-1)!;
    expect(paged.searchParams.get("before")).toBe(firstPage.at(-1)!.created_at);
    expect(paged.searchParams.get("before_id")).toBe(firstPage.at(-1)!.delivery_id);
    // The first page is still on screen: paging is additive, not a replacement.
    expect(screen.getByTestId(`delivery-${firstPage[0].delivery_id}`)).toBeInTheDocument();
  });

  it("removes a subscription after confirmation", async () => {
    let rows = [webhook()];
    server.use(
      http.get(`${BASE}/webhooks`, () => HttpResponse.json(rows)),
      http.delete(`${BASE}/webhooks/:id`, () => {
        rows = [];
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderView();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId(`remove-webhook-${WEBHOOK_ID}`));
    await user.click(await screen.findByTestId(`confirm-remove-webhook-${WEBHOOK_ID}`));

    await waitFor(() =>
      expect(screen.queryByTestId(`webhook-${WEBHOOK_ID}`)).not.toBeInTheDocument(),
    );
  });

  it("surfaces a list failure with a retry", async () => {
    let attempts = 0;
    server.use(
      http.get(`${BASE}/webhooks`, () => {
        attempts += 1;
        if (attempts === 1) {
          return HttpResponse.json(
            { error: { code: "internal_error", message: "boom", details: {} } },
            { status: 500 },
          );
        }
        return HttpResponse.json([webhook()]);
      }),
    );
    renderView();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /retry/i }));

    expect(await screen.findByTestId(`webhook-${WEBHOOK_ID}`)).toBeInTheDocument();
  });

  it("hides the whole surface from a role without manage_webhooks", async () => {
    renderView("member");
    expect(await screen.findByText(/Webhooks unavailable/i)).toBeInTheDocument();
    expect(screen.queryByTestId("register-webhook-card")).not.toBeInTheDocument();
    expect(screen.queryByTestId("create-webhook")).not.toBeInTheDocument();
  });

  it("has no accessibility violations with subscriptions and a delivery log", async () => {
    server.use(
      http.get(`${BASE}/webhooks`, () => HttpResponse.json([webhook()])),
      http.get(`${BASE}/webhooks/:id/deliveries`, () => HttpResponse.json([delivery()])),
    );
    const { container } = renderView();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId(`deliveries-webhook-${WEBHOOK_ID}`));
    await screen.findByTestId(`deliveries-table-${WEBHOOK_ID}`);

    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });

  it("has no accessibility violations in the unauthorized state", async () => {
    const { container } = renderView("viewer");
    await screen.findByText(/Webhooks unavailable/i);
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });
});
