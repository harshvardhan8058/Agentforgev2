/**
 * `Stagger`: staggered entrance for a list of children (cards, rows).
 *
 * Each direct child fades/slides in with a small incremental delay. Under
 * reduced motion / test it renders all children instantly with no animation.
 */
import { motion } from "framer-motion";
import { Children, type ReactNode } from "react";

import { useInstantMotion } from "./motion-config";

export function Stagger({
  children,
  className,
  stepMs = 40,
  "data-testid": testId,
}: {
  children: ReactNode;
  className?: string;
  /** Per-item stagger delay in ms. */
  stepMs?: number;
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
    <div className={className} data-testid={testId}>
      {Children.map(children, (child, index) => (
        <motion.div
          initial={{ opacity: 0, transform: "translateY(6px)" }}
          animate={{ opacity: 1, transform: "translateY(0px)" }}
          transition={{
            duration: 0.2,
            delay: (index * stepMs) / 1000,
            ease: [0.2, 0, 0, 1],
          }}
        >
          {child}
        </motion.div>
      ))}
    </div>
  );
}
