/**
 * Field primitives shared by the login and register views.
 *
 * `AuthField` pairs a label, control and validation message with the wiring that
 * ties them together (`htmlFor`, `aria-invalid`, `aria-describedby`), so every
 * auth field is labelled and every error is announced without each view
 * repeating that plumbing.
 *
 * `PasswordField` adds a reveal toggle. The toggle is a real `<button>` with its
 * own label ("Show password" / "Hide password") — deliberately not "Password",
 * so the field's own accessible name stays unambiguous — and reports state via
 * `aria-pressed`. It is `tabIndex={-1}` so Tab still moves from the password
 * field straight to submit, which is what a keyboard user completing a login
 * expects; the toggle remains reachable by click and by shift-tabbing back.
 */
import type { JSX, ReactNode } from "react";
import { useId, useState } from "react";

import { Input, type InputProps } from "../../components/ui/Input";

export function AuthField({
  id,
  label,
  error,
  hint,
  children,
}: {
  id: string;
  label: string;
  /** Validation message to show, or `null`/`undefined` when the field is valid. */
  error?: string | null;
  hint?: ReactNode;
  /** Receives the wiring the control must spread onto itself. */
  children: (wiring: {
    id: string;
    "aria-invalid": boolean;
    "aria-describedby": string | undefined;
  }) => ReactNode;
}): JSX.Element {
  const errorId = `${id}-error`;
  const invalid = Boolean(error);

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-sm font-medium text-text">
          {label}
        </label>
        {hint}
      </div>
      {children({
        id,
        "aria-invalid": invalid,
        "aria-describedby": invalid ? errorId : undefined,
      })}
      {error && (
        <p id={errorId} className="text-xs text-danger" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

/** Eye / eye-with-slash glyph for the reveal toggle. */
function EyeIcon({ crossed }: { crossed: boolean }): JSX.Element {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-[18px] w-[18px]"
      aria-hidden="true"
    >
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" />
      <circle cx="12" cy="12" r="3" />
      {crossed && <path d="M4 20 20 4" />}
    </svg>
  );
}

export function PasswordField({
  id,
  label,
  error,
  hint,
  ...inputProps
}: {
  id: string;
  label: string;
  error?: string | null;
  hint?: ReactNode;
} & Omit<InputProps, "id" | "type">): JSX.Element {
  const [revealed, setRevealed] = useState(false);
  const statusId = useId();

  return (
    <AuthField id={id} label={label} error={error} hint={hint}>
      {(wiring) => (
        <div className="relative">
          <Input
            {...inputProps}
            {...wiring}
            type={revealed ? "text" : "password"}
            className="h-11 pr-11"
          />
          <button
            type="button"
            // Kept out of the Tab order so Tab goes password -> submit.
            tabIndex={-1}
            onClick={() => setRevealed((current) => !current)}
            aria-label={revealed ? "Hide password" : "Show password"}
            aria-pressed={revealed}
            aria-describedby={statusId}
            className="absolute right-1 top-1/2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-md text-text-subtle transition-colors hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
          >
            <EyeIcon crossed={revealed} />
          </button>
          {/* Announces the change for screen-reader users who toggle it. */}
          <span id={statusId} className="sr-only" aria-live="polite">
            {revealed ? "Password is visible" : "Password is hidden"}
          </span>
        </div>
      )}
    </AuthField>
  );
}
