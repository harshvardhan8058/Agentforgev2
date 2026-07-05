/**
 * `Tooltip`: token-styled tooltip over Radix Tooltip. Export the provider so a
 * single delay-duration group can wrap the app.
 */
import * as RadixTooltip from "@radix-ui/react-tooltip";
import { type ReactNode } from "react";

import { cn } from "../../lib/cn";

export const TooltipProvider = RadixTooltip.Provider;

export function Tooltip({
  children,
  content,
  className,
}: {
  children: ReactNode;
  content: ReactNode;
  className?: string;
}): JSX.Element {
  return (
    <RadixTooltip.Root>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          sideOffset={6}
          className={cn(
            "z-50 rounded-md border border-border bg-surface-raised px-2 py-1 text-xs text-text shadow-elevation-2",
            className,
          )}
        >
          {content}
          <RadixTooltip.Arrow className="fill-[color:var(--color-surface-raised)]" />
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}
