import { afterEach, describe, expect, it } from "vitest";

import { resolveConfig } from "./config";

/**
 * Base-URL resolution, with emphasis on the SAME-ORIGIN mode that keeps the
 * app reachable behind the bundled reverse proxy regardless of the origin it is
 * opened from (localhost / 127.0.0.1 / LAN IP / domain). A hardcoded absolute
 * origin (e.g. `http://localhost`) is the class of bug that produces "Unable to
 * reach the server" when the app is opened from any other origin.
 */
type RuntimeGlobal = { __AGENTFORGE_CONFIG__?: { apiBaseUrl?: string } };

function withRuntime(apiBaseUrl: string | undefined, run: () => void): void {
  const w = window as unknown as RuntimeGlobal;
  w.__AGENTFORGE_CONFIG__ = apiBaseUrl === undefined ? {} : { apiBaseUrl };
  try {
    run();
  } finally {
    delete (window as unknown as RuntimeGlobal).__AGENTFORGE_CONFIG__;
  }
}

afterEach(() => {
  delete (window as unknown as RuntimeGlobal).__AGENTFORGE_CONFIG__;
});

describe("resolveConfig — API base URL resolution", () => {
  it('resolves "/" to the absolute browser origin', () => {
    withRuntime("/", () => {
      expect(resolveConfig({}).baseUrl).toBe(window.location.origin);
    });
  });

  it("treats a slashes-only value as same-origin", () => {
    withRuntime("///", () => {
      expect(resolveConfig({}).baseUrl).toBe(window.location.origin);
    });
  });

  it("uses an absolute runtime URL verbatim, trimming a trailing slash", () => {
    withRuntime("https://api.example.com/", () => {
      expect(resolveConfig({}).baseUrl).toBe("https://api.example.com");
    });
  });

  it("prefers the runtime value over the build-time env", () => {
    withRuntime("/", () => {
      expect(
        resolveConfig({ VITE_API_BASE_URL: "http://build-time:9999" }).baseUrl,
      ).toBe(window.location.origin);
    });
  });

  it("falls back to the build-time env when no runtime value is present", () => {
    withRuntime(undefined, () => {
      expect(
        resolveConfig({ VITE_API_BASE_URL: "http://api.internal:8000" }).baseUrl,
      ).toBe("http://api.internal:8000");
    });
  });

  it("falls back to the documented dev default when nothing is configured", () => {
    expect(resolveConfig({}).baseUrl).toBe("http://localhost:8000");
  });
});
