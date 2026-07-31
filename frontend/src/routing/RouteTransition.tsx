/**
 * `RouteTransition`: a subtle enter animation between protected routes.
 *
 * Keys a `MotionFade` on the current pathname so each navigation replays a
 * short fade/rise of the routed content — the shell (sidebar, top bar) stays
 * mounted and only the content area transitions. `MotionFade` collapses to an
 * instant, no-op render under `prefers-reduced-motion` and in tests, so this
 * never hides content or races assertions.
 */
import type { JSX } from "react";
import { type ReactNode } from "react";
import { useLocation } from "react-router";

import { MotionFade } from "../components/motion/MotionFade";

export function RouteTransition({ children }: { children: ReactNode }): JSX.Element {
  const { pathname } = useLocation();
  return (
    <MotionFade key={pathname} y={6} durationMs={180}>
      {children}
    </MotionFade>
  );
}
