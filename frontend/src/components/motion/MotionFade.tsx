/**
 * `MotionFade`: fade/slide-in entrance for a block of content.
 *
 * Animates only `opacity` and `transform` (GPU-compositable). Under reduced
 * motion / test it renders its children instantly in the final state with no
 * animation, so content is always present for assertions and never hidden.
 */
import { motion } from "framer-motion";
import { type ReactNode } from "react";

import { useInstantMotion } from "./motion-config";

export function MotionFade({
  children,
  className,
  y = 8,
  durationMs = 200,
  "data-testid": testId,
}: {
  children: ReactNode;
  className?: string;
  /** Vertical offset (px) the content rises from. */
  y?: number;
  durationMs?: number;
  "data-testid"?: string;
}): JSX.Element {
  const instant = useInstantMotion();

  if (instant) {
    return (
      <div className={className} data-testid={testId}>
        {children}
      </div>
    );
  }

  return (
    <motion.div
      className={className}
      data-testid={testId}
      initial={{ opacity: 0, transform: `translateY(${y}px)` }}
      animate={{ opacity: 1, transform: "translateY(0px)" }}
      transition={{ duration: durationMs / 1000, ease: [0.2, 0, 0, 1] }}
    >
      {children}
    </motion.div>
  );
}
