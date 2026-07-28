/**
 * `Toast`: token-styled toast primitives over Radix Toast. Provides the
 * provider, viewport, and a styled toast (title + description + close) on a
 * glass surface. The imperative `useToast` API is layered on top in a later
 * task; these are the presentational/accessible primitives.
 */
import type { JSX } from "react";
import * as RadixToast from "@radix-ui/react-toast";
import { X } from "lucide-react";
import { forwardRef, type ComponentPropsWithoutRef } from "react";

import { cn } from "../../lib/cn";

export const ToastProviderPrimitive = RadixToast.Provider;

export const ToastViewport = forwardRef<
  HTMLOListElement,
  ComponentPropsWithoutRef<typeof RadixToast.Viewport>
>(function ToastViewport({ className, ...rest }, ref) {
  return (
    <RadixToast.Viewport
      ref={ref}
      className={cn(
        "fixed bottom-0 right-0 z-[60] m-4 flex w-[calc(100vw-2rem)] max-w-sm flex-col gap-2 outline-none",
        className,
      )}
      {...rest}
    />
  );
});

export type ToastTone = "neutral" | "success" | "danger" | "info";

const TONE_BORDER: Record<ToastTone, string> = {
  neutral: "border-border-strong",
  success: "border-success/60",
  danger: "border-danger/60",
  info: "border-info/60",
};

export function Toast({
  title,
  description,
  tone = "neutral",
  open,
  onOpenChange,
  duration,
}: {
  title: string;
  description?: string;
  tone?: ToastTone;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  duration?: number;
}): JSX.Element {
  return (
    <RadixToast.Root
      open={open}
      onOpenChange={onOpenChange}
      duration={duration}
      className={cn(
        "af-glass flex items-start justify-between gap-3 rounded-lg border p-4 shadow-elevation-3",
        TONE_BORDER[tone],
      )}
    >
      <div className="flex flex-col gap-1">
        <RadixToast.Title className="text-sm font-semibold text-text">
          {title}
        </RadixToast.Title>
        {description && (
          <RadixToast.Description className="text-sm text-text-muted">
            {description}
          </RadixToast.Description>
        )}
      </div>
      <RadixToast.Close
        aria-label="Dismiss"
        className="rounded-md p-1 text-text-muted transition-colors hover:bg-surface-raised hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </RadixToast.Close>
    </RadixToast.Root>
  );
}
