/**
 * `Kbd`: a small keyboard-key hint pill rendered as a semantic `<kbd>`.
 * Uses the mono token family and a subtle raised surface so shortcut hints read
 * as physical keys.
 */
import { type HTMLAttributes } from "react";

import { cn } from "../../lib/cn";

export function Kbd({
  className,
  ...rest
}: HTMLAttributes<HTMLElement>): JSX.Element {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded border border-border bg-surface-raised px-1.5 font-mono text-xs text-text-muted",
        className,
      )}
      {...rest}
    />
  );
}
