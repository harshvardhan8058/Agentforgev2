/**
 * `StreamingCursor`: a blinking cursor shown at the tail of live-streamed tokens.
 *
 * Purely decorative (`aria-hidden`). Under reduced motion / test it renders a
 * static, non-blinking cursor — reduced motion never hides information, it just
 * stops the blink.
 */
import { motion } from "framer-motion";

import { cn } from "../../lib/cn";
import { useInstantMotion } from "./motion-config";

export function StreamingCursor({
  className,
  "data-testid": testId = "streaming-cursor",
}: {
  className?: string;
  "data-testid"?: string;
}): JSX.Element {
  const instant = useInstantMotion();
  const base = cn(
    "inline-block h-[1em] w-[2px] translate-y-[2px] rounded-full bg-primary align-baseline",
    className,
  );

  if (instant) {
    return <span aria-hidden="true" data-testid={testId} className={base} />;
  }

  return (
    <motion.span
      aria-hidden="true"
      data-testid={testId}
      className={base}
      initial={{ opacity: 1 }}
      animate={{ opacity: [1, 1, 0, 0, 1] }}
      transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
    />
  );
}
