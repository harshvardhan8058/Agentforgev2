/**
 * `DropdownMenu`: token-styled menu over Radix DropdownMenu (roving focus,
 * typeahead, `Escape` to close, focus restore, ARIA inherited).
 */
import * as RadixMenu from "@radix-ui/react-dropdown-menu";
import { ChevronsUpDown } from "lucide-react";
import { forwardRef, type ComponentPropsWithoutRef, type ReactNode } from "react";

import { cn } from "../../lib/cn";

export const DropdownMenu = RadixMenu.Root;
export const DropdownMenuTrigger = RadixMenu.Trigger;

/**
 * `DropdownMenuSelectTrigger`: a menu trigger that reads as a select control.
 *
 * The role and team pickers are Radix menus styled as bordered boxes the same
 * height and colour as a text `Input`, with nothing to indicate they open a
 * list. On the API Keys and Members pages they were indistinguishable from
 * fields you were meant to type into — the value just looked like text somebody
 * had already entered. A trailing chevron is the affordance that distinguishes
 * the two, and it is defined once here so no caller can forget it.
 *
 * The icon is `aria-hidden`: the trigger's own role and `aria-expanded` (supplied
 * by Radix) already convey the behaviour assistively.
 */
export const DropdownMenuSelectTrigger = forwardRef<
  HTMLButtonElement,
  Omit<ComponentPropsWithoutRef<typeof RadixMenu.Trigger>, "children"> & {
    /** The current selection, or null/undefined when nothing is chosen. */
    value?: ReactNode;
    /** Shown, de-emphasised, while `value` is empty. */
    placeholder?: string;
  }
>(function DropdownMenuSelectTrigger(
  { className, value, placeholder = "Select…", ...rest },
  ref,
) {
  const empty = value === null || value === undefined || value === "";
  return (
    <RadixMenu.Trigger
      ref={ref}
      className={cn(
        "inline-flex h-10 w-full items-center justify-between gap-2 rounded-md border border-border bg-surface px-3 text-sm text-text",
        "hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...rest}
    >
      <span className={cn("truncate", empty && "text-text-subtle")}>
        {empty ? placeholder : value}
      </span>
      <ChevronsUpDown
        className="h-4 w-4 shrink-0 text-text-subtle"
        aria-hidden="true"
      />
    </RadixMenu.Trigger>
  );
});

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
