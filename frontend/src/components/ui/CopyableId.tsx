/**
 * `CopyableId`: a shortened identifier with a copy control.
 *
 * Generated identifiers are genuinely needed — an org id or run id goes into API
 * calls and support requests — but printing all 36 characters of a UUID spends a
 * whole line on something nobody reads, and offers no way to get it into the
 * clipboard except selecting it by hand. So the middle is elided and a copy
 * button carries the full value.
 *
 * Clipboard access is not guaranteed: `navigator.clipboard` is unavailable
 * outside a secure context, which includes serving the console over plain HTTP
 * on anything other than localhost. That is a realistic deployment, so the copy
 * falls back to a hidden-textarea `execCommand` and, failing even that, reports
 * failure instead of silently doing nothing.
 */
import type { JSX } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";

import { cn } from "../../lib/cn";

/** How long the copied confirmation stays visible. */
const CONFIRM_MS = 1600;

/**
 * Elide the middle of an identifier, keeping enough of both ends to compare two
 * of them by eye.
 *
 * Short values are returned unchanged: shortening `abc` to `a…c` would be longer
 * and less useful than the original.
 */
export function shortenId(value: string, head = 8, tail = 4): string {
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

/** Copy `text`, returning whether it succeeded. */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall through to the legacy path: a rejected promise here usually means
    // permission was denied rather than that the API is missing.
  }
  try {
    // Legacy fallback for a non-secure context. Positioned off-screen rather
    // than `display: none`, which would make it unselectable.
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "-1000px";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}

export function CopyableId({
  value,
  /** Used in the button's accessible name, e.g. "Copy organization id". */
  label = "id",
  testId,
  className,
  /**
   * Show the whole value instead of eliding its middle.
   *
   * Eliding is right for an identifier, which is looked up rather than read, and wrong for a
   * value the operator has to *store*: a webhook signing secret is shown exactly once, and a
   * shortened rendering of it would be unusable if the clipboard is unavailable — which is
   * precisely the deployment this component already has a fallback for.
   */
  full = false,
}: {
  value: string;
  label?: string;
  testId?: string;
  className?: string;
  full?: boolean;
}): JSX.Element {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Clear the pending reset on unmount so it cannot fire against a gone component.
  useEffect(() => {
    return () => {
      if (timer.current !== undefined) clearTimeout(timer.current);
    };
  }, []);

  const onCopy = useCallback(async () => {
    const ok = await copyText(value);
    setState(ok ? "copied" : "failed");
    if (timer.current !== undefined) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), CONFIRM_MS);
  }, [value]);

  return (
    <span
      className={cn("inline-flex items-center gap-1", className)}
      data-testid={testId}
    >
      <code
        className={cn(
          "font-mono text-xs text-text-subtle",
          full ? "break-all" : "truncate",
        )}
        title={value}
        data-testid={testId ? `${testId}-value` : undefined}
      >
        {full ? value : shortenId(value)}
      </code>
      <button
        type="button"
        onClick={() => void onCopy()}
        aria-label={`Copy ${label}`}
        title={`Copy ${label}`}
        data-testid={testId ? `${testId}-copy` : undefined}
        className="rounded p-0.5 text-text-subtle transition-colors hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
      >
        {state === "copied" ? (
          <Check className="h-3.5 w-3.5 text-success" aria-hidden="true" />
        ) : (
          <Copy className="h-3.5 w-3.5" aria-hidden="true" />
        )}
      </button>
      {/* Announced, not just shown as a colour change on the icon. */}
      <span role="status" aria-live="polite" className="sr-only">
        {state === "copied" ? `${label} copied` : ""}
        {state === "failed" ? `Could not copy ${label}` : ""}
      </span>
      {state === "failed" && (
        <span
          className="text-xs text-warning"
          data-testid={testId ? `${testId}-failed` : undefined}
        >
          Copy blocked — select it manually
        </span>
      )}
    </span>
  );
}
