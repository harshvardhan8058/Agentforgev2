import "@testing-library/jest-dom/vitest";
import { afterEach, beforeAll } from "vitest";
import { cleanup } from "@testing-library/react";

// Ensure the DOM is reset between component tests.
afterEach(() => {
  cleanup();
});

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
