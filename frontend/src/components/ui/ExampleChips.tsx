/**
 * `ExampleChips`: a compact row of one-click example prompts.
 *
 * Gives otherwise-empty input surfaces (query, agent, multi-agent) a low-effort
 * starting point — clicking a chip fills the associated field via `onPick`, so
 * a new Operator can see a meaningful result immediately instead of facing a
 * blank field. Purely presentational and keyboard-accessible.
 */

import type { JSX } from "react";
interface ExampleChipsProps {
  /** Leading label (e.g. "Try"). */
  label?: string;
  /** The example strings to offer. */
  examples: readonly string[];
  /** Called with the chosen example text. */
  onPick: (text: string) => void;
  testId?: string;
}

export function ExampleChips({
  label = "Try",
  examples,
  onPick,
  testId = "example-chips",
}: ExampleChipsProps): JSX.Element {
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid={testId}>
      <span className="text-xs font-medium text-text-subtle">{label}:</span>
      {examples.map((example) => (
        <button
          key={example}
          type="button"
          onClick={() => onPick(example)}
          className="rounded-full border border-border bg-surface px-3 py-1 text-xs text-text-muted transition-colors hover:border-border-strong hover:bg-surface-hover hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
        >
          {example}
        </button>
      ))}
    </div>
  );
}
