// @vitest-environment jsdom
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { PromptComparison } from "./PromptComparison";
import { SessionContext } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";

const BASE = "http://localhost:8000";
const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderComparison(versions: number[] = [1, 2]): void {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <SessionContext.Provider value={makeSession("member")}>
        <PromptComparison name="grounded-answer" versions={versions} />
      </SessionContext.Provider>
    </QueryClientProvider>,
  );
}

/** Serve each version's declared variables. */
function versionDetails(byVersion: Record<number, string[]>) {
  return http.get(`${BASE}/prompts/:name`, ({ request }) => {
    const version = Number(new URL(request.url).searchParams.get("version"));
    return HttpResponse.json({
      id: `p-${version}`,
      name: "grounded-answer",
      version,
      body: `body v${version} {{question}}`,
      variables: byVersion[version] ?? [],
      created_at: new Date().toISOString(),
    });
  });
}

/** Serve a rendered result per version. */
function renders(byVersion: Record<number, string>) {
  return http.post(`${BASE}/prompts/:name/render`, async ({ request }) => {
    const body = (await request.json()) as { version: number };
    return HttpResponse.json({
      name: "grounded-answer",
      version: body.version,
      rendered: byVersion[body.version] ?? "",
    });
  });
}

/**
 * A prompt's body is not what you choose between — the rendered result is. Judging that
 * previously meant rendering one version, copying the output away, switching version, and
 * re-entering every variable identically by hand. These tests pin the property that makes
 * the comparison meaningful: the *same* variable values reach both renders.
 */
describe("PromptComparison", () => {
  it("renders nothing when there is only one version to compare", () => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <SessionContext.Provider value={makeSession("member")}>
          <PromptComparison name="grounded-answer" versions={[1]} />
        </SessionContext.Provider>
      </QueryClientProvider>,
    );

    expect(container.firstChild).toBeNull();
  });

  it("defaults to the newest version against the one before it", async () => {
    server.use(versionDetails({ 2: [], 3: [] }));

    renderComparison([1, 2, 3]);

    await waitFor(() =>
      expect(screen.getByTestId("compare-version-a-v2")).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
    expect(screen.getByTestId("compare-version-b-v3")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("asks for the union of both versions' variables", async () => {
    // Versions are independent and may declare different sets; a value is needed for
    // every variable either side references or that render fails.
    server.use(versionDetails({ 1: ["question"], 2: ["question", "tone"] }));

    renderComparison();

    expect(await screen.findByTestId("compare-var-question")).toBeInTheDocument();
    expect(screen.getByTestId("compare-var-tone")).toBeInTheDocument();
  });

  it("sends the same variable values to both renders", async () => {
    // The whole point: inputs held constant so the only difference is the prompt.
    const sent: { version: number; variables: Record<string, string> }[] = [];
    server.use(
      versionDetails({ 1: ["question"], 2: ["question"] }),
      http.post(`${BASE}/prompts/:name/render`, async ({ request }) => {
        const body = (await request.json()) as {
          version: number;
          variables: Record<string, string>;
        };
        sent.push(body);
        return HttpResponse.json({
          name: "grounded-answer",
          version: body.version,
          rendered: `v${body.version}: ${body.variables.question}`,
        });
      }),
    );

    renderComparison();
    await userEvent.type(
      await screen.findByTestId("compare-var-question"),
      "what equipment",
    );
    await userEvent.click(screen.getByTestId("compare-submit"));

    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent.map((s) => s.version).sort()).toEqual([1, 2]);
    expect(sent[0].variables).toEqual({ question: "what equipment" });
    expect(sent[1].variables).toEqual({ question: "what equipment" });
  });

  it("shows both rendered results", async () => {
    server.use(
      versionDetails({ 1: [], 2: [] }),
      renders({ 1: "first result", 2: "second result" }),
    );

    renderComparison();
    await userEvent.click(await screen.findByTestId("compare-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("compare-result")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("compare-output-a").textContent).toContain(
      "first result",
    );
    expect(screen.getByTestId("compare-output-b").textContent).toContain(
      "second result",
    );
  });

  it("diffs the two results when they differ", async () => {
    server.use(
      versionDetails({ 1: [], 2: [] }),
      renders({ 1: "line one\nline two", 2: "line one\nline changed" }),
    );

    renderComparison();
    await userEvent.click(await screen.findByTestId("compare-submit"));

    await waitFor(() => expect(screen.getByTestId("compare-diff")).toBeInTheDocument());
    expect(screen.queryByTestId("compare-identical")).not.toBeInTheDocument();
  });

  it("says so when both versions render identically", async () => {
    // A body change that makes no difference to this case is a real, useful finding —
    // and an empty diff would look like a failure.
    server.use(
      versionDetails({ 1: [], 2: [] }),
      renders({ 1: "same output", 2: "same output" }),
    );

    renderComparison();
    await userEvent.click(await screen.findByTestId("compare-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("compare-identical")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("compare-diff")).not.toBeInTheDocument();
  });

  it("blocks comparing while a variable is unsupplied", async () => {
    // Mirrors the render form: never issue a request that cannot succeed (Property 12).
    server.use(versionDetails({ 1: ["question"], 2: ["question"] }));

    renderComparison();
    // Wait for the variable to be known: the button is also disabled while the two
    // version details load, so asserting on it alone could pass for the wrong reason.
    await screen.findByTestId("compare-var-question");

    expect(screen.getByTestId("compare-missing-prompt").textContent).toContain(
      "question",
    );
    expect(screen.getByTestId("compare-submit")).toBeDisabled();
  });

  it("blocks comparing a version with itself", async () => {
    server.use(versionDetails({ 1: [], 2: [] }));

    renderComparison();
    await userEvent.click(await screen.findByTestId("compare-version-a-v2"));

    expect(screen.getByTestId("compare-same-version")).toBeInTheDocument();
    expect(screen.getByTestId("compare-submit")).toBeDisabled();
  });

  it("fills the variables it has suggestions for", async () => {
    server.use(versionDetails({ 1: ["question"], 2: ["question"] }));

    renderComparison();
    await userEvent.click(await screen.findByTestId("compare-fill-example"));

    expect(screen.getByTestId("compare-var-question")).not.toHaveValue("");
    expect(screen.getByTestId("compare-submit")).toBeEnabled();
  });

  it("notes when neither version declares variables", async () => {
    server.use(versionDetails({ 1: [], 2: [] }));

    renderComparison();

    expect(await screen.findByTestId("compare-no-variables")).toBeInTheDocument();
    expect(screen.getByTestId("compare-submit")).toBeEnabled();
  });

  it("surfaces a render failure", async () => {
    server.use(
      versionDetails({ 1: [], 2: [] }),
      http.post(`${BASE}/prompts/:name/render`, () =>
        HttpResponse.json(
          {
            error: {
              code: "missing_variable",
              message: "Missing variable.",
              details: {},
            },
          },
          { status: 400 },
        ),
      ),
    );

    renderComparison();
    await userEvent.click(await screen.findByTestId("compare-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("compare-error")).toBeInTheDocument(),
    );
  });
});
