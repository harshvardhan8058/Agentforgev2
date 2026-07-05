// @vitest-environment node
import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from "vitest";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { apiClient } from "./client";
import {
  setToken,
  getToken,
  setUnauthenticatedHandler,
  __resetTokenStoreForTests,
} from "../auth/tokenStore";

const BASE = "http://localhost:8000";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  __resetTokenStoreForTests();
  setUnauthenticatedHandler(null);
});
afterAll(() => server.close());

/**
 * Task 5.5 — MSW integration test for the refresh flow end-to-end.
 * _Requirements: 3.3, 3.5, 3.6_
 */
describe("auth middleware refresh flow (MSW)", () => {
  it("401 → refresh → retry → 200 succeeds transparently", async () => {
    let documentsCalls = 0;
    let refreshCalls = 0;

    server.use(
      http.get(`${BASE}/documents`, ({ request }) => {
        documentsCalls += 1;
        const auth = request.headers.get("Authorization");
        if (documentsCalls === 1) {
          return HttpResponse.json(
            { error: { code: "unauthorized", message: "Token expired.", details: {} } },
            { status: 401 },
          );
        }
        // Second attempt must carry the refreshed token.
        expect(auth).toBe("Bearer refreshed-token");
        return HttpResponse.json({ documents: [] }, { status: 200 });
      }),
      http.post(`${BASE}/auth/refresh`, () => {
        refreshCalls += 1;
        return HttpResponse.json(
          { access_token: "refreshed-token", token_type: "bearer" },
          { status: 200 },
        );
      }),
    );

    setToken("expired-token");
    const { response, data } = await apiClient.GET("/documents");

    expect(response.status).toBe(200);
    expect(data).toEqual({ documents: [] });
    expect(refreshCalls).toBe(1);
    expect(documentsCalls).toBe(2);
    // Token was replaced with the refreshed one.
    expect(getToken()).toBe("refreshed-token");
  });

  it("401 → refresh-401 clears the session and routes to login", async () => {
    let refreshCalls = 0;
    const onUnauthenticated = vi.fn();
    setUnauthenticatedHandler(onUnauthenticated);

    server.use(
      http.get(`${BASE}/documents`, () =>
        HttpResponse.json(
          { error: { code: "unauthorized", message: "Token expired.", details: {} } },
          { status: 401 },
        ),
      ),
      http.post(`${BASE}/auth/refresh`, () => {
        refreshCalls += 1;
        return HttpResponse.json(
          { error: { code: "unauthorized", message: "Refresh failed.", details: {} } },
          { status: 401 },
        );
      }),
    );

    setToken("expired-token");
    const { response } = await apiClient.GET("/documents");

    expect(response.status).toBe(401);
    expect(refreshCalls).toBe(1);
    expect(onUnauthenticated).toHaveBeenCalledTimes(1);
    // Session cleared.
    expect(getToken()).toBeNull();
  });
});
