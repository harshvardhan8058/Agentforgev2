/**
 * `AuthLayout`: the premium, centered chrome shared by the login and register
 * views.
 *
 * Delivers a commercial-grade auth surface (not a bare form): a branded mark, a
 * clear display title + supporting copy, and a glass (backdrop-blurred) card
 * with the solid WCAG-AA contrast fallback (`af-glass`, defined in globals.css).
 * The layout is fully responsive and centered, with generous rhythm. It is
 * presentational only — the views own all Backend_API interaction.
 */
import type { JSX } from "react";
import { type ReactNode } from "react";

import { MotionFade } from "../../components/motion/MotionFade";

export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
  testId,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer?: ReactNode;
  testId?: string;
}): JSX.Element {
  return (
    <main
      data-testid={testId}
      className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-bg px-4 py-10 text-text"
    >
      {/* Ambient brand backdrop — purely decorative. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-70"
        style={{
          background:
            "radial-gradient(60rem 60rem at 50% -10%, color-mix(in oklab, var(--color-primary) 18%, transparent), transparent)",
        }}
      />

      <MotionFade className="relative z-10 w-full max-w-md">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-primary-fg shadow-elevation-2">
            <span className="text-lg font-bold">A</span>
          </span>
          <div className="flex flex-col gap-1">
            <h1 className="text-3xl font-semibold tracking-tight text-text">
              {title}
            </h1>
            <p className="text-sm text-text-muted">{subtitle}</p>
          </div>
        </div>

        <div className="af-glass rounded-2xl border border-border-strong p-6 shadow-elevation-4 sm:p-8">
          {children}
        </div>

        {footer && (
          <div className="mt-6 text-center text-sm text-text-muted">{footer}</div>
        )}
      </MotionFade>
    </main>
  );
}
