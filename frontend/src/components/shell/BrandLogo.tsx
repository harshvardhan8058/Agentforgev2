/**
 * `BrandLogo`: the AgentForge brand mark.
 *
 * A crisp geometric "forge spark" glyph on a gradient tile, paired with the
 * wordmark. `compact` renders the tile alone (for the collapsed sidebar rail).
 * The mark is decorative; the accessible product name is exposed via the
 * wordmark text (or the `aria-label` when compact).
 */
import type { JSX } from "react";
import { cn } from "../../lib/cn";

function ForgeMark({ className }: { className?: string }): JSX.Element {
  return (
    <span
      className={cn(
        "relative flex items-center justify-center overflow-hidden rounded-lg bg-gradient-brand shadow-elevation-1",
        className,
      )}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        className="h-[62%] w-[62%] text-white"
        aria-hidden="true"
      >
        {/* Stylized spark / upward chevron — the "forge" igniting. */}
        <path
          d="M12 2.5 4.5 13h5l-1.8 8.5L19.5 10h-5l1.6-7.5z"
          fill="currentColor"
          fillOpacity="0.95"
        />
      </svg>
    </span>
  );
}

export function BrandLogo({
  compact = false,
  className,
}: {
  compact?: boolean;
  className?: string;
}): JSX.Element {
  return (
    <div
      className={cn("flex items-center gap-2.5", className)}
      data-testid="brand-mark"
      aria-label={compact ? "AgentForge" : undefined}
    >
      <ForgeMark className="h-8 w-8" />
      {!compact && (
        <span className="text-[0.95rem] font-semibold tracking-tight text-text">
          Agent<span className="text-primary">Forge</span>
        </span>
      )}
    </div>
  );
}
