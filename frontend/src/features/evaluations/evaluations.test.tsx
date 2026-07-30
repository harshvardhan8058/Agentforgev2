// @vitest-environment jsdom
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { EvaluationsView } from "./EvaluationsView";
import { SessionContext } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";
import type { Role } from "../../auth/token";

const BASE = "http://localhost:8000";
const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderView(role: Role = "member"): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <SessionContext.Provider value={makeSession(role)}>
        <EvaluationsView />
      </SessionContext.Provider>
    </QueryClientProvider>,
  );
}

/**
 * Task 24.3 (evaluations) — _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_
 */
describe("EvaluationsView (MSW)", () => {
  it("lists datasets with name + created-at (14.2)", async () => {
    server.use(
      http.get(`${BASE}/evaluations/datasets`, () =>
        HttpResponse.json([
          {
            dataset_id: "ds-1",
            name: "smoke",
            created_at: "2024-01-01T00:00:00Z",
            item_count: 3,
          },
        ]),
      ),
    );

    renderView("member");
    await waitFor(() => expect(screen.getByTestId("dataset-ds-1")).toBeInTheDocument());
    expect(screen.getByTestId("dataset-name-cell").textContent).toBe("smoke");
    expect(screen.getByTestId("dataset-created-at").textContent).toBe("2024-01-01T00:00:00Z");
    expect(screen.getByTestId("dataset-item-count-badge").textContent).toBe("3 items");
  });

  it("flags a dataset with no items, which can only ever score 0", async () => {
    server.use(
      http.get(`${BASE}/evaluations/datasets`, () =>
        HttpResponse.json([
          {
            dataset_id: "ds-empty",
            name: "empty",
            created_at: "2024-01-01T00:00:00Z",
            item_count: 0,
          },
        ]),
      ),
    );

    renderView("member");

    await waitFor(() =>
      expect(screen.getByTestId("dataset-item-count-badge").textContent).toBe("empty"),
    );
  });

  it("creates a dataset and shows the returned id (14.1)", async () => {
    let created = 0;
    server.use(
      http.get(`${BASE}/evaluations/datasets`, () => HttpResponse.json([])),
      http.post(`${BASE}/evaluations/datasets`, async ({ request }) => {
        created += 1;
        const body = (await request.json()) as { name: string };
        return HttpResponse.json({ dataset_id: "ds-new", name: body.name });
      }),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(await screen.findByTestId("dataset-name"), "regression");
    await user.click(screen.getByTestId("create-dataset-submit"));

    await waitFor(() => expect(created).toBe(1));
    await waitFor(() =>
      expect(screen.getByTestId("create-dataset-result").textContent).toContain("ds-new"),
    );
  });

  it("sends the entered items, not an empty list (the defect this fixes)", async () => {
    // Regression test: the body used to be `{ name, items: [] }` unconditionally,
    // so every dataset was created empty and every run over it scored 0.
    let sent: { name: string; items: unknown[] } | null = null;
    server.use(
      http.get(`${BASE}/evaluations/datasets`, () => HttpResponse.json([])),
      http.post(`${BASE}/evaluations/datasets`, async ({ request }) => {
        sent = (await request.json()) as { name: string; items: unknown[] };
        return HttpResponse.json({ dataset_id: "ds-new", name: sent.name });
      }),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(await screen.findByTestId("dataset-name"), "regression");
    await user.type(screen.getByTestId("dataset-item-input-0"), "the question");
    await user.type(screen.getByTestId("dataset-item-expected-0"), "the answer");
    await user.click(screen.getByTestId("create-dataset-submit"));

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent).toEqual({
      name: "regression",
      items: [{ input: "the question", expected: "the answer" }],
    });
  });

  it("selects the newly created dataset for the run form", async () => {
    // The id is generated server-side; before this it had to be read off the
    // list and retyped into the run form by hand.
    server.use(
      http.get(`${BASE}/evaluations/datasets`, () => HttpResponse.json([])),
      http.post(`${BASE}/evaluations/datasets`, () =>
        HttpResponse.json({ dataset_id: "ds-generated-id", name: "n" }),
      ),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(await screen.findByTestId("dataset-name"), "n");
    await user.type(screen.getByTestId("dataset-item-input-0"), "q");
    await user.click(screen.getByTestId("create-dataset-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("run-dataset-id")).toHaveValue("ds-generated-id"),
    );
  });

  it("runs evaluators and shows aggregate + per-item scores (14.3)", async () => {
    server.use(
      http.get(`${BASE}/evaluations/datasets`, () => HttpResponse.json([])),
      http.post(`${BASE}/evaluations/runs`, async ({ request }) => {
        const body = (await request.json()) as { dataset_id: string; evaluators: string[] };
        expect(body.dataset_id).toBe("ds-1");
        expect(body.evaluators).toEqual(["exact_match"]);
        return HttpResponse.json({
          run_id: "run-1",
          dataset_id: "ds-1",
          aggregate_score: 0.75,
          results: [{ item_id: "it-1", evaluator: "exact_match", score: 0.75 }],
        });
      }),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(await screen.findByTestId("run-dataset-id"), "ds-1");
    await user.type(screen.getByTestId("run-evaluators"), "exact_match");
    await user.click(screen.getByTestId("create-run-submit"));

    await waitFor(() => expect(screen.getByTestId("run-result")).toBeInTheDocument());
    expect(screen.getByTestId("run-aggregate").textContent).toContain("0.75");
    expect(screen.getByTestId("run-result-scores-item-score-0").textContent).toBe("0.75");
  });

  it("opens a persisted run showing aggregate + per-item scores (14.4)", async () => {
    server.use(
      http.get(`${BASE}/evaluations/datasets`, () => HttpResponse.json([])),
      http.get(`${BASE}/evaluations/runs/run-9`, () =>
        HttpResponse.json({
          run_id: "run-9",
          dataset_id: "ds-1",
          aggregate_score: 0.5,
          results: [{ item_id: "it-1", evaluator: "bleu", score: 0.5 }],
        }),
      ),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(await screen.findByTestId("view-run-id"), "run-9");
    await user.click(screen.getByTestId("open-run-submit"));

    await waitFor(() => expect(screen.getByTestId("run-detail")).toBeInTheDocument());
    expect(screen.getByTestId("run-detail-aggregate").textContent).toContain("0.5");
    expect(screen.getByTestId("run-detail-scores-item-score-0").textContent).toBe("0.5");
  });

  it("presents a cross-org/absent run as not found (14.5)", async () => {
    server.use(
      http.get(`${BASE}/evaluations/datasets`, () => HttpResponse.json([])),
      http.get(`${BASE}/evaluations/runs/missing`, () =>
        HttpResponse.json(
          { error: { code: "not_found", message: "Run not found.", details: {} } },
          { status: 404 },
        ),
      ),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(await screen.findByTestId("view-run-id"), "missing");
    await user.click(screen.getByTestId("open-run-submit"));

    await waitFor(() => expect(screen.getByTestId("run-detail-error")).toBeInTheDocument());
    expect(screen.getByTestId("error-banner")).toHaveTextContent("Run not found.");
  });
});
