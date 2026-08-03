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

import { DeliveryQueuePanel } from "./DeliveryQueuePanel";
import { ToastProvider } from "../../providers/ToastProvider";

const BASE = "http://localhost:8000";
const server = setupServer();

expect.extend({ toHaveNoViolations });

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// jsdom computes no layout, so contrast is unverifiable here (the Playwright axe lane covers it).
const AXE_OPTIONS = { rules: { "color-contrast": { enabled: false } } };

const PENDING_ID = "11111111-1111-4111-8111-111111111111";
const ABANDONED_ID = "22222222-2222-4222-8222-222222222222";

function renderPanel(): ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <DeliveryQueuePanel orgId="org-1" />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function entry(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    entry_id: PENDING_ID,
    webhook_id: "33333333-3333-4333-8333-333333333333",
    event: "run.completed",
    status: "pending",
    attempts: 2,
    next_attempt_at: new Date(Date.now() + 120_000).toISOString(),
    last_error: "endpoint returned HTTP 503",
    idempotency_key: "run.completed:r1",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

function summary(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return { pending: 0, abandoned: 0, entries: [], ...overrides };
}

/**
 * The delivery queue: what has not arrived yet, and what gave up.
 * The operator-facing half of durable delivery — before the outbox there was nothing to show.
 */
describe("DeliveryQueuePanel (MSW)", () => {
  beforeEach(() => {
    server.use(http.get(`${BASE}/webhooks/queue`, () => HttpResponse.json(summary())));
  });

  it("says everything is delivered when the queue is empty", async () => {
    renderPanel();
    expect(await screen.findByTestId("webhook-queue-empty")).toHaveTextContent(
      /Everything has been delivered/i,
    );
    expect(screen.queryByTestId("webhook-queue-table")).not.toBeInTheDocument();
  });

  it("renders a skeleton while loading", async () => {
    server.use(
      http.get(`${BASE}/webhooks/queue`, async () => {
        await new Promise((resolve) => setTimeout(resolve, 30));
        return HttpResponse.json(summary());
      }),
    );
    renderPanel();
    expect(screen.getByTestId("webhook-queue-skeleton")).toBeInTheDocument();
    await screen.findByTestId("webhook-queue-empty");
  });

  it("reports whole-queue totals, not just the page", async () => {
    server.use(
      http.get(`${BASE}/webhooks/queue`, () =>
        HttpResponse.json(summary({ pending: 12, abandoned: 3, entries: [entry()] })),
      ),
    );
    renderPanel();

    const counts = await screen.findByTestId("webhook-queue-counts");
    expect(counts).toHaveTextContent("12 waiting");
    expect(counts).toHaveTextContent("3 gave up");
  });

  it("shows a pending entry with its next attempt and no redeliver button", async () => {
    server.use(
      http.get(`${BASE}/webhooks/queue`, () =>
        HttpResponse.json(summary({ pending: 1, entries: [entry()] })),
      ),
    );
    renderPanel();

    const row = await screen.findByTestId(`queue-entry-${PENDING_ID}`);
    expect(within(row).getByText("run.completed")).toBeInTheDocument();
    expect(within(row).getByText("Waiting")).toBeInTheDocument();
    expect(within(row).getByText(/endpoint returned HTTP 503/)).toBeInTheDocument();
    // Already scheduled: offering a redelivery would invite a duplicate.
    expect(screen.queryByTestId(`redeliver-${PENDING_ID}`)).not.toBeInTheDocument();
  });

  it("shows an abandoned entry with a redeliver button and no next attempt", async () => {
    server.use(
      http.get(`${BASE}/webhooks/queue`, () =>
        HttpResponse.json(
          summary({
            abandoned: 1,
            entries: [
              entry({
                entry_id: ABANDONED_ID,
                status: "abandoned",
                attempts: 8,
                event: "budget.threshold_crossed",
                last_error: "ConnectTimeout: the endpoint did not answer",
              }),
            ],
          }),
        ),
      ),
    );
    renderPanel();

    const row = await screen.findByTestId(`queue-entry-${ABANDONED_ID}`);
    expect(within(row).getByText("Gave up")).toBeInTheDocument();
    expect(within(row).getByText("8")).toBeInTheDocument();
    expect(within(row).getByText("—")).toBeInTheDocument();
    expect(screen.getByTestId(`redeliver-${ABANDONED_ID}`)).toBeInTheDocument();
  });

  it("redelivers an abandoned entry and refreshes the queue", async () => {
    let redelivered = false;
    server.use(
      http.get(`${BASE}/webhooks/queue`, () =>
        HttpResponse.json(
          redelivered
            ? summary({ pending: 1, entries: [entry()] })
            : summary({
                abandoned: 1,
                entries: [entry({ entry_id: ABANDONED_ID, status: "abandoned" })],
              }),
        ),
      ),
      http.post(`${BASE}/webhooks/queue/:id/redeliver`, () => {
        redelivered = true;
        return HttpResponse.json(entry({ attempts: 0 }));
      }),
    );
    renderPanel();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId(`redeliver-${ABANDONED_ID}`));

    expect(await screen.findByText(/Queued for redelivery/i)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId(`queue-entry-${PENDING_ID}`)).toBeInTheDocument(),
    );
  });

  it("surfaces a refused redelivery rather than failing silently", async () => {
    server.use(
      http.get(`${BASE}/webhooks/queue`, () =>
        HttpResponse.json(
          summary({
            abandoned: 1,
            entries: [entry({ entry_id: ABANDONED_ID, status: "abandoned" })],
          }),
        ),
      ),
      http.post(`${BASE}/webhooks/queue/:id/redeliver`, () =>
        HttpResponse.json(
          {
            error: {
              code: "not_redeliverable",
              message: "Only an abandoned delivery can be redelivered; this one is pending.",
              details: { status: "pending" },
            },
          },
          { status: 409 },
        ),
      ),
    );
    renderPanel();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId(`redeliver-${ABANDONED_ID}`));

    expect(await screen.findByText(/Only an abandoned delivery/i)).toBeInTheDocument();
  });

  it("surfaces a load failure with a retry", async () => {
    let attempts = 0;
    server.use(
      http.get(`${BASE}/webhooks/queue`, () => {
        attempts += 1;
        if (attempts === 1) {
          return HttpResponse.json(
            { error: { code: "internal_error", message: "boom", details: {} } },
            { status: 500 },
          );
        }
        return HttpResponse.json(summary({ pending: 1, entries: [entry()] }));
      }),
    );
    renderPanel();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /retry/i }));

    expect(await screen.findByTestId(`queue-entry-${PENDING_ID}`)).toBeInTheDocument();
  });

  it("can be refreshed on demand", async () => {
    let calls = 0;
    server.use(
      http.get(`${BASE}/webhooks/queue`, () => {
        calls += 1;
        return HttpResponse.json(summary());
      }),
    );
    renderPanel();
    const user = userEvent.setup();
    await screen.findByTestId("webhook-queue-empty");

    await user.click(screen.getByTestId("refresh-webhook-queue"));

    await waitFor(() => expect(calls).toBe(2));
  });

  it("has no accessibility violations with a populated queue", async () => {
    server.use(
      http.get(`${BASE}/webhooks/queue`, () =>
        HttpResponse.json(
          summary({
            pending: 1,
            abandoned: 1,
            entries: [
              entry(),
              entry({ entry_id: ABANDONED_ID, status: "abandoned", attempts: 8 }),
            ],
          }),
        ),
      ),
    );
    const { container } = renderPanel();
    await screen.findByTestId("webhook-queue-table");

    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });
});
