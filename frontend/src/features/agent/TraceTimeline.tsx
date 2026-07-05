/**
 * `TraceTimeline`: an ordered, observability-grade timeline of trace entries
 * (Req 9.5, 6.3).
 *
 * Renders each `TraceEntryModel` — step type, optional tool call, role, and
 * outcome — in ascending `ordinal` order with tokenized styling. When the trace
 * carries no exported detail (e.g. tracing configured NoOp), the caller passes
 * an empty list and this component marks the trace detail **unavailable** while
 * still rendering the surrounding run data (graceful degradation, Req 6.3).
 */
import { Wrench } from "lucide-react";

import { Badge } from "../../components/ui/Badge";

export interface TraceEntry {
  ordinal: number;
  step_type: string;
  role_id?: string | null;
  tool_name?: string | null;
  outcome?: string | null;
}

export function TraceTimeline({
  entries,
}: {
  entries: readonly TraceEntry[];
}): JSX.Element {
  if (entries.length === 0) {
    return (
      <p
        className="text-sm text-text-muted"
        data-testid="trace-detail-unavailable"
      >
        Trace detail unavailable.
      </p>
    );
  }

  const ordered = [...entries].sort((a, b) => a.ordinal - b.ordinal);

  return (
    <ol className="flex flex-col gap-2" data-testid="trace-timeline">
      {ordered.map((entry, i) => (
        <li
          key={`${entry.ordinal}-${i}`}
          data-testid={`trace-entry-${entry.ordinal}`}
          data-ordinal={entry.ordinal}
          className="flex items-start gap-3 rounded-md border border-border bg-surface p-3"
        >
          <span className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface-raised text-xs font-medium text-text-muted">
            {entry.ordinal}
          </span>
          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className="text-sm font-medium text-text"
                data-testid="trace-step-type"
              >
                {entry.step_type}
              </span>
              {entry.role_id && (
                <Badge tone="info" data-testid="trace-role">
                  {entry.role_id}
                </Badge>
              )}
              {entry.tool_name && (
                <Badge tone="primary" data-testid="trace-tool">
                  <Wrench className="h-3 w-3" aria-hidden="true" />
                  {entry.tool_name}
                </Badge>
              )}
            </div>
            {entry.outcome && (
              <p className="text-xs text-text-muted" data-testid="trace-outcome">
                {entry.outcome}
              </p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
