// @vitest-environment jsdom
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { GuardrailsView } from "./GuardrailsView";
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
        <GuardrailsView />
      </SessionContext.Provider>
    </QueryClientProvider>,
  );
}

/**
 * Task 24.3 (guardrails) — _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_
 */
describe("GuardrailsView (MSW)", () => {
  it("renders guardrails in the returned order (13.1)", async () => {
    server.use(
      http.get(`${BASE}/guardrails/config`, () =>
        HttpResponse.json({
          guardrails: [
            { name: "profanity", kind: "KeywordGuardrail" },
            { name: "pii", kind: "RegexGuardrail" },
          ],
        }),
      ),
    );

    renderView("member");
    await waitFor(() => expect(screen.getByTestId("guardrails-list")).toBeInTheDocument());
    expect(screen.getByTestId("guardrail-name-0").textContent).toBe("profanity");
    expect(screen.getByTestId("guardrail-kind-0").textContent).toBe("KeywordGuardrail");
    expect(screen.getByTestId("guardrail-name-1").textContent).toBe("pii");
  });

  it("renders an empty no-active-guardrails state (13.5)", async () => {
    server.use(http.get(`${BASE}/guardrails/config`, () => HttpResponse.json({ guardrails: [] })));
    renderView("member");
    await waitFor(() => expect(screen.getByTestId("guardrails-empty")).toBeInTheDocument());
  });

  it("shows an allow decision (13.2)", async () => {
    server.use(
      http.get(`${BASE}/guardrails/config`, () => HttpResponse.json({ guardrails: [] })),
      http.post(`${BASE}/guardrails/evaluate`, () =>
        HttpResponse.json({ decision: "allow", flags: [] }),
      ),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(await screen.findByTestId("guardrail-content"), "hello");
    await user.click(screen.getByTestId("evaluate-submit"));

    await waitFor(() => expect(screen.getByTestId("evaluate-result")).toBeInTheDocument());
    expect(screen.getByTestId("decision-badge").textContent).toBe("allow");
  });

  it("shows flags + reason for a flag decision (13.3)", async () => {
    server.use(
      http.get(`${BASE}/guardrails/config`, () => HttpResponse.json({ guardrails: [] })),
      http.post(`${BASE}/guardrails/evaluate`, () =>
        HttpResponse.json({ decision: "flag", flags: ["toxicity"], reason: "borderline tone" }),
      ),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(await screen.findByTestId("guardrail-content"), "content");
    await user.click(screen.getByTestId("evaluate-submit"));

    await waitFor(() => expect(screen.getByTestId("evaluate-result")).toBeInTheDocument());
    expect(screen.getByTestId("decision-badge").textContent).toBe("flag");
    expect(screen.getByTestId("decision-flag-toxicity")).toBeInTheDocument();
    expect(screen.getByTestId("decision-reason").textContent).toBe("borderline tone");
  });

  it("shows the reason for a block decision (13.4)", async () => {
    server.use(
      http.get(`${BASE}/guardrails/config`, () => HttpResponse.json({ guardrails: [] })),
      http.post(`${BASE}/guardrails/evaluate`, () =>
        HttpResponse.json({ decision: "block", flags: [], reason: "prohibited content" }),
      ),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(await screen.findByTestId("guardrail-content"), "bad");
    await user.click(screen.getByTestId("evaluate-submit"));

    await waitFor(() => expect(screen.getByTestId("evaluate-result")).toBeInTheDocument());
    expect(screen.getByTestId("decision-badge").textContent).toBe("block");
    expect(screen.getByTestId("decision-reason").textContent).toBe("prohibited content");
  });

  it("omits the evaluate control without run_agents", async () => {
    server.use(http.get(`${BASE}/guardrails/config`, () => HttpResponse.json({ guardrails: [] })));
    renderView("viewer");
    await waitFor(() => expect(screen.getByTestId("guardrails-config-card")).toBeInTheDocument());
    expect(screen.queryByTestId("evaluate-card")).toBeNull();
  });
});
