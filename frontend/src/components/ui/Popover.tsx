/**
 * `Popover`: token-styled popover over Radix Popover (focus trap + restore,
 * `Escape` to close, ARIA inherited). Content sits on a glass overlay surface
 * with the solid WCAG-AA fallback.
 */
import * as RadixPopover from "@radix-ui/react-popover";
import { forwardRef, type ComponentPropsWithoutRef } from "react";

import { cn } from "../../lib/cn";

export const Popover = RadixPopover.Root;
export const PopoverTrigger = RadixPopover.Trigger;
export const PopoverAnchor = RadixPopover.Anchor;

export const PopoverContent = forwardRef<
  HTMLDivElement,
  ComponentPropsWithoutRef<typeof RadixPopover.Content>
>(function PopoverContent({ className, sideOffset = 6, ...rest }, ref) {
  return (
    <RadixPopover.Portal>
      <RadixPopover.Content
        ref={ref}
        sideOffset={sideOffset}
        className={cn(
          "af-glass z-50 min-w-[12rem] rounded-lg border border-border-strong p-3 shadow-elevation-3",
          "focus:outline-none",
          className,
        )}
        {...rest}
      />
    </RadixPopover.Portal>
  );
});
