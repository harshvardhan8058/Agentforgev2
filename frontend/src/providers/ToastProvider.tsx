/**
 * `ToastProvider`: owns the toast queue and renders the Radix Toast viewport.
 *
 * Exposes the imperative `useToast` API (`toast(...)` / `dismiss(...)`) to the
 * whole app. Each queued toast renders as a token-styled `Toast` on a glass
 * surface with an `aria-live` region inherited from Radix, so transient
 * outcomes are announced without blocking (Req 5.4, 6.5, 7.5).
 */
import type { JSX } from "react";
import { useCallback, useMemo, useRef, useState, type ReactNode } from "react";

import {
  Toast,
  ToastProviderPrimitive,
  ToastViewport,
} from "../components/ui/Toast";
import { ToastContext, type ToastApi, type ToastOptions } from "../hooks/useToast";

interface QueuedToast extends ToastOptions {
  id: string;
  open: boolean;
}

const DEFAULT_DURATION_MS = 5000;

export function ToastProvider({ children }: { children: ReactNode }): JSX.Element {
  const [toasts, setToasts] = useState<QueuedToast[]>([]);
  const counter = useRef(0);

  const dismiss = useCallback((id: string): void => {
    setToasts((current) =>
      current.map((t) => (t.id === id ? { ...t, open: false } : t)),
    );
  }, []);

  const remove = useCallback((id: string): void => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback((options: ToastOptions): string => {
    counter.current += 1;
    const id = `toast-${counter.current}`;
    setToasts((current) => [...current, { ...options, id, open: true }]);
    return id;
  }, []);

  const api = useMemo<ToastApi>(() => ({ toast, dismiss }), [toast, dismiss]);

  return (
    <ToastContext.Provider value={api}>
      <ToastProviderPrimitive swipeDirection="right">
        {children}
        {toasts.map((t) => (
          <Toast
            key={t.id}
            title={t.title}
            description={t.description}
            tone={t.tone}
            open={t.open}
            duration={t.durationMs ?? DEFAULT_DURATION_MS}
            onOpenChange={(open) => {
              if (!open) {
                dismiss(t.id);
                // Allow the exit before dropping from the queue.
                window.setTimeout(() => remove(t.id), 200);
              }
            }}
          />
        ))}
        <ToastViewport />
      </ToastProviderPrimitive>
    </ToastContext.Provider>
  );
}
