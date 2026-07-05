/**
 * `useToast` + the toast context type.
 *
 * An imperative toast API layered over the Radix `Toast` UI primitive. Features
 * call `toast({ title, description, tone })` to surface a transient,
 * non-blocking outcome (copied, saved, approved, rate-limited); the
 * `ToastProvider` owns the queue and renders the Radix viewport.
 */
import { createContext, useContext } from "react";

import type { ToastTone } from "../components/ui/Toast";

/** Options for an imperatively-raised toast. */
export interface ToastOptions {
  title: string;
  description?: string;
  tone?: ToastTone;
  /** Auto-dismiss duration in ms (defaults to the provider's value). */
  durationMs?: number;
}

/** The imperative toast API exposed to components. */
export interface ToastApi {
  /** Raise a toast; returns the generated toast id. */
  toast(options: ToastOptions): string;
  /** Dismiss a specific toast early. */
  dismiss(id: string): void;
}

export const ToastContext = createContext<ToastApi | null>(null);

/** Access the imperative toast API. Must be used within a `ToastProvider`. */
export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (ctx === null) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return ctx;
}
