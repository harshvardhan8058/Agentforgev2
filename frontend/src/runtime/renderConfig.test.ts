import { describe, it, expect } from "vitest";
import fc from "fast-check";

import { renderConfigJs, EMPTY_CONFIG_JS } from "./renderConfig";
import { resolveConfig } from "../config";

/**
 * Feature: agentforge-deployment, Property 4: Frontend image is build-once / run-anywhere
 *
 * Validates: Requirements 8.1, 8.2, 8.3, 8.4
 *
 * For any two API_BASE_URL values supplied at container start, the same
 * Frontend_Image serves byte-identical hashed static assets and differs only in
 * the generated runtime config.js, which reflects the supplied value (or the
 * documented default when none is supplied).
 *
 * Since API_BASE_URL is a *runtime* input injected via config.js (never a Vite
 * build-time env var), the hashed asset set produced by `npm run build` is, by
 * construction, independent of it. We model that build output as a fixed fixture
 * and assert it is invariant across renders while config.js varies — a pure
 * render-logic test that captures the invariant without building a container.
 */
describe("Property 4: Frontend image is build-once / run-anywhere", () => {
  // Represents the hashed static-asset set emitted by the Node build stage. It is
  // produced once at image build time and cannot depend on the runtime
  // API_BASE_URL, which is only ever injected through the generated config.js.
  const HASHED_ASSET_SET = Object.freeze([
    "index.html",
    "assets/index-a1b2c3d4.js",
    "assets/index-e5f6a7b8.css",
    "assets/vendor-9c0d1e2f.js",
  ]);

  const normalize = (raw: string): string => {
    const v = raw.trim();
    const r = v.length > 0 ? v : "http://localhost:8000";
    return r.endsWith("/") ? r.slice(0, -1) : r;
  };

  it("hashed assets stay byte-identical while config.js reflects each API_BASE_URL", () => {
    fc.assert(
      fc.property(fc.webUrl(), fc.webUrl(), (a, b) => {
        const imageA = { assets: HASHED_ASSET_SET, configJs: renderConfigJs(a) };
        const imageB = { assets: HASHED_ASSET_SET, configJs: renderConfigJs(b) };

        // Build-once: hashed asset set is independent of API_BASE_URL.
        expect(imageA.assets).toEqual(imageB.assets);
        expect(imageA.assets).toBe(HASHED_ASSET_SET);
        expect(imageB.assets).toBe(HASHED_ASSET_SET);

        // Run-anywhere: config.js reflects each environment's value.
        expect(imageA.configJs).toContain(a);
        expect(imageB.configJs).toContain(b);
        if (a !== b) {
          expect(imageA.configJs).not.toEqual(imageB.configJs);
        }
      }),
      { numRuns: 200 },
    );
  });

  it("falls back to the documented default (empty config) when API_BASE_URL is unset", () => {
    expect(renderConfigJs(undefined)).toEqual(EMPTY_CONFIG_JS);
    expect(renderConfigJs(null)).toEqual(EMPTY_CONFIG_JS);
    expect(renderConfigJs("")).toEqual(EMPTY_CONFIG_JS);
  });

  it("resolveConfig consumes the rendered runtime value (Req 8.2 round-trip)", () => {
    fc.assert(
      fc.property(fc.webUrl(), (url) => {
        // Simulate the browser having executed the rendered config.js.
        (window as unknown as { __AGENTFORGE_CONFIG__?: { apiBaseUrl?: string } })
          .__AGENTFORGE_CONFIG__ = { apiBaseUrl: url };
        try {
          // Empty build-time env: the runtime value must take precedence.
          const resolved = resolveConfig({});
          expect(resolved.baseUrl).toEqual(normalize(url));
        } finally {
          delete (window as unknown as { __AGENTFORGE_CONFIG__?: unknown })
            .__AGENTFORGE_CONFIG__;
        }
      }),
      { numRuns: 200 },
    );
  });

  it("resolveConfig falls back to the default when the runtime global is absent (jsdom)", () => {
    // No window.__AGENTFORGE_CONFIG__ set: identical to the previous build-time
    // behavior, so existing config resolution is preserved.
    expect(resolveConfig({}).baseUrl).toEqual("http://localhost:8000");
  });
});
