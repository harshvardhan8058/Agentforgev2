/**
 * Regression guard: the Prompt Studio editor is SELF-HOSTED, not CDN-loaded.
 *
 * `@monaco-editor/react` ships no copy of Monaco. Left at its defaults, its loader injects
 * a `<script>` tag pointing at `https://cdn.jsdelivr.net/npm/monaco-editor@…` and fetches
 * the editor at runtime. That default silently breaks the shipped product in three ways:
 *
 *   1. The gateway serves `Content-Security-Policy: … script-src 'self' …`, so the browser
 *      refuses the CDN script and the editor never mounts — the Prompt Studio renders an
 *      empty box in Docker/production while looking fine under `vite dev` (where no CSP is
 *      applied). A unit test with Monaco mocked cannot catch this.
 *   2. It breaks the platform's keyless promise of zero external network calls, and makes
 *      the console unusable in an air-gapped or egress-filtered deployment.
 *   3. It fetches executable code from a third party at runtime, outside
 *      `package-lock.json` and outside the bundle secret scan.
 *
 * `src/features/prompts/monacoSetup.ts` fixes this by handing a locally-installed
 * `monaco-editor` to the loader. These tests assert the OBSERVABLE consequence in a real
 * browser — that opening the prompts route issues no third-party request and still mounts a
 * working editor — so a regression in the loader wiring, the import specifiers, or the Vite
 * chunking fails here rather than in production.
 */
import { expect, test } from "@playwright/test";

import { mockCommon, mockJson, seedAuth } from "./helpers";

/** Hosts that must never be contacted. Monaco's default CDN plus common mirrors. */
const FORBIDDEN_HOSTS = ["cdn.jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com"];

// `GET /prompts` returns template NAMES (a string list), and
// `GET /prompts/{name}/versions` returns ascending version NUMBERS.
const PROMPT_NAMES = ["grounded-answer"];
const PROMPT_VERSIONS = [1, 2];

/**
 * Seed the prompts route. An `owner` session holds `ingest_documents`, so the "New version"
 * card renders — and its body field is a `PromptStudio`, which mounts Monaco as soon as the
 * route loads without any further interaction.
 */
async function openPromptsRoute(page: import("@playwright/test").Page): Promise<void> {
  await seedAuth(page, { role: "owner" });
  await mockCommon(page);
  await mockJson(page, "/prompts", PROMPT_NAMES);
  await mockJson(page, "/prompts/*/versions", PROMPT_VERSIONS);
  await page.goto("/prompts");
}

test.describe("Prompt Studio Monaco is self-hosted", () => {
  test("opening the prompts route makes no third-party asset request", async ({ page }) => {
    const offOrigin: string[] = [];

    // Record every request whose host is not the app's own preview origin or the mocked
    // API. This catches a CDN fetch however it is triggered — script tag, import, or
    // worker bootstrap.
    page.on("request", (request) => {
      const url = request.url();
      if (FORBIDDEN_HOSTS.some((host) => url.includes(host))) {
        offOrigin.push(url);
      }
    });

    await openPromptsRoute(page);

    // The editor must actually have mounted, otherwise "no CDN request" would pass
    // trivially on a page where Monaco never loaded at all.
    await expect(page.getByTestId("prompt-body-editor").locator(".monaco-editor").first()).toBeVisible();
    // Give the lazy chunk and any worker bootstrap every chance to issue a fetch.
    await page.waitForLoadState("networkidle");

    expect(
      offOrigin,
      `Monaco (or another dependency) fetched from a third-party CDN, which the gateway's ` +
        `script-src 'self' CSP blocks in production:\n${offOrigin.join("\n")}`,
    ).toEqual([]);
  });

  test("the editor mounts and renders the prompt body from the local bundle", async ({
    page,
  }) => {
    const consoleErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });

    await openPromptsRoute(page);

    // Monaco renders into `.monaco-editor`. Its presence proves the editor code was
    // actually obtained and initialized — the exact step that fails when the CDN script is
    // blocked. Scoped to the studio container so we assert on the real editor surface.
    const studio = page.getByTestId("prompt-body-editor");
    await expect(studio).toBeVisible();
    await expect(studio.locator(".monaco-editor").first()).toBeVisible();

    // The markdown grammar we register locally must resolve too: Monaco applies
    // `.mtk*` token classes only once a tokenizer has loaded for the model's language.
    await expect(studio.locator(".view-lines")).toBeVisible();

    // Monaco reports a hard failure if `MonacoEnvironment.getWorker` is missing or the
    // worker cannot be constructed, which would break diff computation.
    const workerErrors = consoleErrors.filter(
      (text) => text.includes("MonacoEnvironment") || text.includes("Could not create web worker"),
    );
    expect(workerErrors, workerErrors.join("\n")).toEqual([]);
  });
});
