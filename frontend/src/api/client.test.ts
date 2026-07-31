import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { runPackageBin } from "../../scripts/node-bin.mjs";

import { apiClient } from "./client";
import type { paths } from "./schema";

const here = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(here, "..", "..");

/**
 * Task 2.1 — contract-fidelity check for the generated client.
 * _Requirements: 1.2, 1.3_
 */
describe("API_Client contract fidelity", () => {
  it("exposes the openapi-fetch verbs as the sole call surface (Req 1.2)", () => {
    expect(typeof apiClient.GET).toBe("function");
    expect(typeof apiClient.POST).toBe("function");
    expect(typeof apiClient.PUT).toBe("function");
    expect(typeof apiClient.DELETE).toBe("function");
  });

  it("is typed by the generated schema — known shipped paths exist (Req 1.3)", () => {
    // These are compile-time contract assertions: if any of these endpoints
    // were absent from the generated schema, `tsc --noEmit` (npm run typecheck)
    // would fail. They double as a runtime sanity list of shipped contracts.
    const shippedPaths: (keyof paths)[] = [
      "/auth/login",
      "/query",
      "/documents",
      "/agent/run",
      "/agent/stream",
      "/multi-agent/runs",
      "/analytics/usage",
      "/prompts",
      "/guardrails/config",
      "/evaluations/datasets",
      "/conversations",
    ];
    expect(shippedPaths.length).toBeGreaterThan(0);
  });

  it(
    "regenerates schema.d.ts deterministically from openapi.json (Req 1.3)",
    () => {
      // Invokes the pinned generator with the current Node binary rather than via
      // `npx`, which cannot be spawned on Windows (see scripts/node-bin.mjs).
      const runCodegen = (): string =>
        runPackageBin("openapi-typescript", ["./openapi.json"], {
          cwd: frontendRoot,
          stderr: "ignore",
        });

      const first = runCodegen();
      const second = runCodegen();
      // Codegen output is deterministic across repeated runs.
      expect(first).toEqual(second);

      // ...and matches the committed generated file. Line endings are normalized
      // first: `.gitattributes` pins `eol=lf` so a fresh checkout is LF on every
      // OS, but a checkout predating that rule holds CRLF and would fail on every
      // line, which looks like codegen drift and is not.
      const normalize = (text: string): string => text.replace(/\r\n/g, "\n").trim();
      const committed = readFileSync(
        resolve(frontendRoot, "src", "api", "schema.d.ts"),
        "utf-8",
      );
      expect(normalize(first)).toEqual(normalize(committed));
    },
    // Spawns the generator twice. That is ~1s total on Linux CI but several
    // seconds per run on Windows, which overran Vitest's 5s default — the
    // failure only became reachable once the `npx` ENOENT crash was fixed.
    // Matches the 180_000 budget the bundle-secret build already uses.
    120_000,
  );
});
