/**
 * `FallbackNotice`: explains the built-in keyless `fallback` LLM provider.
 *
 * When no external LLM credential is configured, the backend answers with a
 * deterministic `fallback` provider. Surfacing that plainly — with a pointer to
 * enabling a real provider — turns a confusing `provider: fallback` label into
 * an understood, expected state. Rendered only when a response's provider is
 * the fallback provider.
 */
import type { JSX } from "react";
import { Info } from "lucide-react";

export function FallbackNotice(): JSX.Element {
  return (
    <div
      data-testid="fallback-notice"
      className="flex items-start gap-2 rounded-lg border border-border bg-surface-raised px-3 py-2 text-xs text-text-muted"
    >
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-text-subtle" aria-hidden="true" />
      <span>
        Answered by the built-in{" "}
        <span className="font-medium text-text">fallback</span> provider —
        deterministic and fully keyless. Configure an LLM provider key (e.g.{" "}
        <code className="rounded bg-bg-subtle px-1 py-0.5 font-mono">GROQ_API_KEY</code>
        ) to get model-generated responses.
      </span>
    </div>
  );
}
