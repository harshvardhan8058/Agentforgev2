import "@testing-library/jest-dom/vitest";
import { afterEach, beforeAll } from "vitest";
import { cleanup } from "@testing-library/react";
import { Blob as NodeBlob, File as NodeFile } from "node:buffer";

/**
 * Align the file/multipart globals with the `fetch` implementation.
 *
 * jsdom installs its own `Blob`, `File` and `FormData` over Node's. `fetch`
 * (undici) is NOT jsdom's, so a multipart upload built from jsdom classes and
 * sent through `fetch` crosses two incompatible realms. Undici's multipart
 * parser constructs each entry with the *global* `File` and then brand-checks
 * the result against its own class, so with jsdom's `File` installed it rejects
 * the very object it just built:
 *
 *     assert(typeof value === "string" && webidl.is.USVString(value)
 *            || webidl.is.File(value))
 *       at multipartFormDataParser (node:internal/deps/undici/undici)
 *
 * On Node 22 this was masked: `new Response(...).blob()` returned a Node `Blob`,
 * so a per-test-file "recover the classes from a Response" trick happened to
 * work. On Node 24 that same call returns *jsdom's* `Blob`, so the trick
 * silently recovers the wrong class and uploads fail with a bare network error.
 * The repair therefore has to be explicit rather than derived.
 *
 * `Blob` and `File` come straight from `node:buffer` (the classes backing the
 * globals in a plain Node process). `FormData` has no core-module export, so it
 * is recovered by parsing a multipart body — which is only safe *after* `File`
 * is correct, hence the ordering below.
 *
 * Applied only under jsdom; test files using the `node` environment already have
 * the right globals and must not be touched.
 */
if (typeof window !== "undefined") {
  const g = globalThis as unknown as Record<string, unknown>;
  g.Blob = NodeBlob;
  g.File = NodeFile;

  const boundary = "----agentforge-formdata-probe";
  const probeBody =
    `--${boundary}\r\n` +
    `Content-Disposition: form-data; name="f"; filename="probe.txt"\r\n` +
    `Content-Type: text/plain\r\n\r\n` +
    `probe\r\n` +
    `--${boundary}--\r\n`;
  const probe = await new Response(probeBody, {
    headers: { "content-type": `multipart/form-data; boundary=${boundary}` },
  }).formData();
  g.FormData = probe.constructor;
}

// Ensure the DOM is reset between component tests.
afterEach(() => {
  cleanup();
});

// NOTE: a console filter used to live here to silence the two React Router v7
// future-flag advisories. Under React Router 8 that behaviour is the default and
// the advisories are no longer emitted, so the filter was removed rather than
// left in place — console warnings are now surfaced unfiltered.

/**
 * Deterministic UI environment:
 *  - jsdom has no `matchMedia`; provide a stub so ThemeProvider and the motion
 *    layer can query preferences without throwing. It reports
 *    `prefers-reduced-motion: reduce` so Framer Motion collapses to instant.
 *  - Force the motion primitives to their instant/no-op path via the global
 *    flag, so component tests never race animations.
 */
beforeAll(() => {
  globalThis.__AF_INSTANT_MOTION__ = true;

  if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
    window.matchMedia = (query: string): MediaQueryList => {
      const reduced = /prefers-reduced-motion/.test(query);
      return {
        matches: reduced,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      } as unknown as MediaQueryList;
    };
  }

  // jsdom lacks several DOM APIs that Radix primitives (Dialog/Popover/
  // DropdownMenu via Popper) rely on. Provide inert stubs so overlay
  // primitives can open, trap focus, and be keyboard-operated under test.
  if (typeof globalThis.ResizeObserver === "undefined") {
    globalThis.ResizeObserver = class {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    } as unknown as typeof ResizeObserver;
  }

  if (typeof Element !== "undefined") {
    Element.prototype.scrollIntoView =
      Element.prototype.scrollIntoView || (() => {});
    Element.prototype.hasPointerCapture =
      Element.prototype.hasPointerCapture || (() => false);
    Element.prototype.setPointerCapture =
      Element.prototype.setPointerCapture || (() => {});
    Element.prototype.releasePointerCapture =
      Element.prototype.releasePointerCapture || (() => {});
  }

  if (typeof window !== "undefined" && typeof window.PointerEvent === "undefined") {
    window.PointerEvent = window.MouseEvent as unknown as typeof PointerEvent;
  }
});
