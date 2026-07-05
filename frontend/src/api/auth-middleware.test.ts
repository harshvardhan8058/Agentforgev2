import { describe, it, expect } from "vitest";
import fc from "fast-check";

import {
  authorizationFor,
  isPublicAuthPath,
  executeWithRefreshPolicy,
  type RefreshPolicyHooks,
} from "./auth-middleware";

const PUBLIC = ["/auth/login", "/auth/register-self"] as const;
const AUTHED = [
  "/query",
  "/documents",
  "/agent/run",
  "/multi-agent/runs",
  "/analytics/usage",
  "/prompts",
  "/auth/refresh",
] as const;

describe("api/auth-middleware — bearer attachment", () => {
  // Feature: agentforge-frontend, Property 7: Every authenticated request carries the bearer token
  it("Property 7: every authenticated request carries the bearer token", () => {
    const pathArb = fc.constantFrom(...PUBLIC, ...AUTHED);
    const tokenArb = fc.option(fc.string(), { nil: null });

    fc.assert(
      fc.property(pathArb, tokenArb, (path, token) => {
        const header = authorizationFor(path, token);
        if (isPublicAuthPath(path)) {
          expect(header).toBeNull();
          return;
        }
        if (token === null || token.length === 0) {
          expect(header).toBeNull();
        } else {
          expect(header).toBe(`Bearer ${token}`);
        }
      }),
      { numRuns: 200 },
    );
  });
});

describe("api/auth-middleware — bounded 401 refresh policy", () => {
  // Feature: agentforge-frontend, Property 6: The 401 refresh path retries at most once
  it("Property 6: the 401 refresh path retries at most once", () => {
    const scenarioArb = fc.record({
      firstStatus: fc.constantFrom(200, 401, 403, 500),
      refreshToken: fc.option(fc.string({ minLength: 1 }), { nil: null }),
      secondStatus: fc.constantFrom(200, 401, 500),
    });

    fc.assert(
      fc.asyncProperty(scenarioArb, async (scenario) => {
        const statuses = [scenario.firstStatus, scenario.secondStatus];
        let sendIndex = 0;
        let refreshCount = 0;
        let clearedCount = 0;

        const hooks: RefreshPolicyHooks = {
          initialToken: () => "initial-token",
          send: async () => {
            const status = statuses[Math.min(sendIndex, statuses.length - 1)];
            sendIndex += 1;
            return status;
          },
          refresh: async () => {
            refreshCount += 1;
            return scenario.refreshToken;
          },
          onCleared: () => {
            clearedCount += 1;
          },
        };

        const result = await executeWithRefreshPolicy(hooks);

        // Hard bounds: never loops.
        expect(result.refreshCalls).toBeLessThanOrEqual(1);
        expect(result.attempts).toBeLessThanOrEqual(2);
        expect(refreshCount).toBeLessThanOrEqual(1);
        expect(clearedCount).toBeLessThanOrEqual(1);

        if (scenario.firstStatus !== 401) {
          expect(result.attempts).toBe(1);
          expect(result.refreshCalls).toBe(0);
          expect(result.finalStatus).toBe(scenario.firstStatus);
          expect(result.cleared).toBe(false);
        } else if (scenario.refreshToken === null) {
          // Refresh failed → clear + route, one attempt, one refresh.
          expect(result.refreshCalls).toBe(1);
          expect(result.attempts).toBe(1);
          expect(result.cleared).toBe(true);
          expect(clearedCount).toBe(1);
        } else {
          // Refresh ok → retry exactly once.
          expect(result.refreshCalls).toBe(1);
          expect(result.attempts).toBe(2);
          expect(result.finalStatus).toBe(scenario.secondStatus);
          expect(result.cleared).toBe(scenario.secondStatus === 401);
        }
      }),
      { numRuns: 200 },
    );
  });
});
