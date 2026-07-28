/**
 * `ScoreBars`: a lightweight aggregate + per-item score visualization for
 * evaluation runs (Req 14.3, 14.4).
 *
 * Uses tokenized bars (transform/width driven by the score in `0..1`) rather
 * than the heavy lazy chart layer, keeping the view deterministic and keyless
 * under test while still visualizing the scores. The authoritative numeric
 * scores are always shown as text alongside each bar.
 */

import type { JSX } from "react";
interface ItemScore {
  item_id: string;
  evaluator: string;
  score: number;
}

/** Clamp a score into a 0..100 width percentage for the bar. */
function widthPct(score: number): number {
  if (!Number.isFinite(score)) return 0;
  return Math.max(0, Math.min(100, score * 100));
}

export function ScoreBars({
  aggregate,
  results,
  testId = "score-bars",
}: {
  aggregate: number;
  results: ItemScore[];
  testId?: string;
}): JSX.Element {
  return (
    <div className="flex flex-col gap-2" data-testid={testId}>
      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between text-xs text-text-muted">
          <span>Aggregate</span>
          <span className="tabular-nums" data-testid={`${testId}-aggregate`}>
            {aggregate}
          </span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-bg-subtle">
          <div
            className="h-full rounded-full bg-primary"
            style={{ width: `${widthPct(aggregate)}%` }}
          />
        </div>
      </div>

      {results.length > 0 && (
        <ul className="flex flex-col gap-1.5" data-testid={`${testId}-items`}>
          {results.map((r, i) => (
            <li key={`${r.item_id}-${r.evaluator}-${i}`} data-testid={`${testId}-item-${i}`}>
              <div className="flex items-center justify-between text-xs text-text-muted">
                <span className="font-mono">{r.evaluator}</span>
                <span className="tabular-nums" data-testid={`${testId}-item-score-${i}`}>
                  {r.score}
                </span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-bg-subtle">
                <div
                  className="h-full rounded-full bg-accent"
                  style={{ width: `${widthPct(r.score)}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
