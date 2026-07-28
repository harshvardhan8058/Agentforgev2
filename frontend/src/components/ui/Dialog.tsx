/**
 * `Dialog`: a token-styled modal over Radix Dialog.
 *
 * Focus trapping, focus restoration on close, `Escape`-to-close, ARIA roles,
 * and scroll locking are inherited from Radix. The content sits on a **glass**
 * overlay surface (`af-glass`) with the solid WCAG-AA fallback declared in
 * globals.css.
 */
import type { JSX } from "react";
import * as RadixDialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { type ReactNode } from "react";

import { cn } from "../../lib/cn";

export const Dialog = RadixDialog.Root;
export const DialogTrigger = RadixDialog.Trigger;
export const DialogClose = RadixDialog.Close;

export function DialogContent({
  children,
  className,
  title,
  description,
  showClose = true,
}: {
  children: ReactNode;
  className?: string;
  /** Accessible title (rendered; required for a11y). */
  title: string;
  description?: string;
  showClose?: boolean;
}): JSX.Element {
  return (
    <RadixDialog.Portal>
      <RadixDialog.Overlay className="fixed inset-0 z-40 bg-black/50 data-[state=open]:animate-in" />
      <RadixDialog.Content
        className={cn(
          "af-glass fixed left-1/2 top-1/2 z-50 w-[92vw] max-w-lg -translate-x-1/2 -translate-y-1/2",
          "rounded-xl border border-border-strong p-6 shadow-elevation-4 focus:outline-none",
          className,
        )}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div className="flex flex-col gap-1">
            <RadixDialog.Title className="text-lg font-semibold text-text">
              {title}
            </RadixDialog.Title>
            {description ? (
              <RadixDialog.Description className="text-sm text-text-muted">
                {description}
              </RadixDialog.Description>
            ) : (
              <RadixDialog.Description className="sr-only">
                {title}
              </RadixDialog.Description>
            )}
          </div>
          {showClose && (
            <RadixDialog.Close
              aria-label="Close"
              className="rounded-md p-1 text-text-muted transition-colors hover:bg-surface-raised hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </RadixDialog.Close>
          )}
        </div>
        {children}
      </RadixDialog.Content>
    </RadixDialog.Portal>
  );
}
