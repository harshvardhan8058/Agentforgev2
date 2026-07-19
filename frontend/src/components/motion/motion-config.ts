/**
 * Motion configuration shared by the `components/motion/` primitives.
 *
 * Motion is **reduced-motion aware** and **test-swappable**: when the operator
 * requests reduced motion (`prefers-reduced-motion: reduce`) — or when a global
 * test flag forces it — the primitives collapse to an instant, no-op transition
 * so information is never hidden and component tests never race animations.
 */
import { useReducedMotion } from "framer-motion";

/**
 * A global flag the test setup (or an operator preference layer) can set to
 * force all motion primitives to render instantly, independent of matchMedia.
 */
declare global {
  var __AF_INSTANT_MOTION__: boolean | undefined;
}

/** True when animations should be instant/no-op (reduced motion or test flag). */
export function useInstantMotion(): boolean {
  const prefersReduced = useReducedMotion();
  const forced =
    typeof globalThis !== "undefined" && globalThis.__AF_INSTANT_MOTION__ === true;
  return forced || prefersReduced === true;
}
