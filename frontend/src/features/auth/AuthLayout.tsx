/**
 * `AuthLayout`: the premium split-screen chrome shared by the login and
 * register views.
 *
 * Two panels on large viewports: a decorative brand panel that states what the
 * product does, and the form panel. Below `lg` the brand panel is dropped
 * entirely (not merely hidden with CSS that still costs layout) and a compact
 * brand mark heads the form instead, so the small-screen experience stays a
 * single focused column rather than a squeezed two-up.
 *
 * Accessibility notes, since this page is covered by an axe check that allows
 * no serious violations:
 * - The form panel is the `<main>` landmark; the brand panel is
 *   `aria-hidden` decoration with no interactive content, so nothing is
 *   reachable only from the visually hidden side.
 * - Foreground text sits on solid token surfaces, never on the aurora blobs, so
 *   contrast is deterministic regardless of where the animated blobs drift.
 * - All motion is CSS that collapses under `prefers-reduced-motion`.
 *
 * Presentational only — the views own every Backend_API interaction.
 */
import type { JSX } from "react";
import { type ReactNode } from "react";

import { MotionFade } from "../../components/motion/MotionFade";

/** A capability highlight shown on the brand panel. */
interface Highlight {
  /** Inline SVG path data for the 24x24 icon. */
  readonly icon: string;
  readonly title: string;
  readonly body: string;
}

const HIGHLIGHTS: readonly Highlight[] = [
  {
    icon: "M12 3v3m0 12v3m9-9h-3M6 12H3m13.5-6.5-2 2m-7 7-2 2m11 0-2-2m-7-7-2-2",
    title: "Multi-agent orchestration",
    body: "Planner, Researcher, Writer and Critic collaborate, and you watch every role stream live.",
  },
  {
    icon: "M4 5h16M4 12h10M4 19h7m6-3 4 4-4 4",
    title: "Answers grounded in your documents",
    body: "Retrieval-backed responses carry citations to the exact passages they came from.",
  },
  {
    icon: "M12 3 4 6.5v5c0 4.5 3.4 8.7 8 9.5 4.6-.8 8-5 8-9.5v-5L12 3Zm-1.5 9.5 1.5 1.5 3-3",
    title: "Governed by default",
    body: "Guardrails, role-based access and a full audit trail on every run.",
  },
];

/** The brand mark: a rounded gradient tile with the AgentForge monogram. */
function BrandMark({ className = "" }: { className?: string }): JSX.Element {
  return (
    <span
      className={`flex items-center justify-center rounded-xl text-primary-fg shadow-elevation-2 ${className}`}
      style={{ background: "var(--gradient-brand)" }}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="h-1/2 w-1/2"
        aria-hidden="true"
      >
        {/* A stylised anvil/spark: "forging" agents. */}
        <path d="M13 2 4.5 13H11l-1 9 9.5-11H13l1-9Z" />
      </svg>
    </span>
  );
}

/** The decorative brand panel. Rendered only at `lg` and above. */
function BrandPanel(): JSX.Element {
  return (
    <section
      aria-hidden="true"
      className="relative hidden overflow-hidden bg-bg-subtle lg:flex lg:flex-col lg:justify-between lg:p-12 xl:p-16"
    >
      {/* Aurora field + grid texture: decoration beneath all content. */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <span
          className="af-aurora-blob"
          style={{
            top: "-14%",
            left: "-10%",
            width: "34rem",
            height: "34rem",
            background: "var(--color-primary)",
          }}
        />
        <span
          className="af-aurora-blob"
          style={{
            bottom: "-18%",
            right: "-12%",
            width: "30rem",
            height: "30rem",
            background: "var(--color-accent)",
          }}
        />
        <span
          className="af-aurora-blob"
          style={{
            top: "38%",
            left: "34%",
            width: "22rem",
            height: "22rem",
            background: "var(--color-role-planner)",
            opacity: 0.32,
          }}
        />
        <span className="af-grid-overlay absolute inset-0" />
      </div>

      <div className="relative z-10 flex items-center gap-3">
        <BrandMark className="h-10 w-10" />
        <span className="text-lg font-semibold tracking-tight text-text">
          AgentForge
        </span>
      </div>

      <div className="relative z-10 flex flex-col gap-10">
        <div className="flex flex-col gap-4">
          <h2 className="max-w-lg text-4xl font-semibold leading-tight tracking-tight text-text">
            The agent platform that shows its work.
          </h2>
          <p className="max-w-md text-base leading-relaxed text-text-muted">
            Build, run and govern retrieval-grounded agents — with the plan, the
            sources and the critique visible on every run.
          </p>
        </div>

        <ul className="flex max-w-md flex-col gap-5">
          {HIGHLIGHTS.map((item) => (
            <li key={item.title} className="flex gap-4">
              <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface text-primary">
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="h-[18px] w-[18px]"
                >
                  <path d={item.icon} />
                </svg>
              </span>
              <span className="flex flex-col gap-1">
                <span className="text-sm font-semibold text-text">
                  {item.title}
                </span>
                <span className="text-sm leading-relaxed text-text-muted">
                  {item.body}
                </span>
              </span>
            </li>
          ))}
        </ul>
      </div>

      <p className="relative z-10 flex items-center gap-2 text-xs text-text-subtle">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-success" />
        Runs keyless out of the box — add provider keys only when you want them.
      </p>
    </section>
  );
}

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
    <div className="min-h-screen bg-bg text-text lg:grid lg:grid-cols-[1.05fr_1fr] xl:grid-cols-[1.15fr_1fr]">
      <BrandPanel />

      <main
        data-testid={testId}
        className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden px-5 py-12 sm:px-8"
      >
        {/* A restrained wash so the form side is not flat, kept well below the
            card so text contrast is unaffected. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 lg:hidden"
          style={{
            background:
              "radial-gradient(42rem 32rem at 50% -8%, var(--color-primary-subtle), transparent)",
          }}
        />

        <MotionFade className="relative z-10 flex w-full max-w-[26rem] flex-col">
          {/* The brand panel is absent below lg, so the mark appears here. */}
          <div className="mb-8 flex flex-col items-center gap-3 text-center lg:hidden">
            <BrandMark className="h-11 w-11" />
            <span className="text-sm font-semibold tracking-tight text-text">
              AgentForge
            </span>
          </div>

          <header className="mb-7 flex flex-col gap-2 text-center lg:text-left">
            <h1 className="text-3xl font-semibold tracking-tight text-text">
              {title}
            </h1>
            <p className="text-sm leading-relaxed text-text-muted">{subtitle}</p>
          </header>

          <div className="rounded-2xl border border-border bg-surface p-6 shadow-elevation-3 sm:p-7">
            {children}
          </div>

          {footer && (
            <div className="mt-6 text-center text-sm text-text-muted">
              {footer}
            </div>
          )}
        </MotionFade>
      </main>
    </div>
  );
}
