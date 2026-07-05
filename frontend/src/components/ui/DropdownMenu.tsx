/**
 * `DropdownMenu`: token-styled menu over Radix DropdownMenu (roving focus,
 * typeahead, `Escape` to close, focus restore, ARIA inherited).
 */
import * as RadixMenu from "@radix-ui/react-dropdown-menu";
import { forwardRef, type ComponentPropsWithoutRef } from "react";

import { cn } from "../../lib/cn";

export const DropdownMenu = RadixMenu.Root;
export const DropdownMenuTrigger = RadixMenu.Trigger;

export const DropdownMenuContent = forwardRef<
  HTMLDivElement,
  ComponentPropsWithoutRef<typeof RadixMenu.Content>
>(function DropdownMenuContent({ className, sideOffset = 6, ...rest }, ref) {
  return (
    <RadixMenu.Portal>
      <RadixMenu.Content
        ref={ref}
        sideOffset={sideOffset}
        className={cn(
          "af-glass z-50 min-w-[10rem] rounded-lg border border-border-strong p-1 shadow-elevation-3",
          "focus:outline-none",
          className,
        )}
        {...rest}
      />
    </RadixMenu.Portal>
  );
});

export const DropdownMenuItem = forwardRef<
  HTMLDivElement,
  ComponentPropsWithoutRef<typeof RadixMenu.Item>
>(function DropdownMenuItem({ className, ...rest }, ref) {
  return (
    <RadixMenu.Item
      ref={ref}
      className={cn(
        "flex cursor-pointer select-none items-center gap-2 rounded-md px-2 py-1.5 text-sm text-text outline-none",
        "data-[highlighted]:bg-surface-raised data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
        className,
      )}
      {...rest}
    />
  );
});

export const DropdownMenuSeparator = forwardRef<
  HTMLDivElement,
  ComponentPropsWithoutRef<typeof RadixMenu.Separator>
>(function DropdownMenuSeparator({ className, ...rest }, ref) {
  return (
    <RadixMenu.Separator
      ref={ref}
      className={cn("my-1 h-px bg-border", className)}
      {...rest}
    />
  );
});
