import type { JSX } from "react";

import type { Example } from "../../lib/examples";

/**
 * `ExampleChips`: a compact row of one-click presets for an input.
 *
 * Gives otherwise-blank input surfaces a low-effort starting point — clicking a
 * chip fills the associated field via `onPick`, so an Operator can see a
 * meaningful result immediately instead of facing an empty field and guessing
 * what the product expects.
 *
 * Chips accept either a bare string or an `{ label, value }` pair. The pair form
 * exists because several presets are full sentences: rendering those verbatim
 * produced a wall of long pills that was hard to scan, so the label carries a
 * short name while the value — the text actually inserted — is available as the
 * chip's `title` and as its accessible description.
 *
 * Purely presentational and keyboard-accessible.
 */
interface ExampleChipsProps {
  /** Leading label (e.g. "Try"). */
  label?: string;
  /** The presets to offer, as plain strings or `{ label, value }` pairs. */
  examples: readonly (string | Example)[];
  /** Called with the chosen preset's value. */
  onPick: (text: string) => void;
  testId?: string;
}

/** Normalize either accepted shape to `{ label, value }`. */
function toExample(example: string | Example): Example {
  return typeof example === "string"
    ? { label: example, value: example }
    : example;
}

export function ExampleChips({
  label = "Try",
  examples,
  onPick,
  testId = "example-chips",
}: ExampleChipsProps): JSX.Element {
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid={testId}>
      <span className="text-xs font-medium text-text-subtle">{label}:</span>
      {examples.map((example) => {
        const { label: chipLabel, value } = toExample(example);
        return (
          <button
            key={chipLabel}
            type="button"
            onClick={() => onPick(value)}
            // Only add a title when it would say something the label does not.
            title={value === chipLabel ? undefined : value}
            className="rounded-full border border-border bg-surface px-2.5 py-1 text-xs text-text-muted transition-colors hover:border-primary/60 hover:bg-primary-subtle hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
          >
            {chipLabel}
          </button>
        );
      })}
    </div>
  );
}
