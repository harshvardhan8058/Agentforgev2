/**
 * Pure single-agent SSE reducer (Property 8).
 *
 * `singleAgentReduce` folds parsed frames into an accumulated state that keeps
 * non-terminal events (`step`/`tool_call`/`delta`) in received order,
 * transitions to `closed` on the FIRST terminal event (`completion` or
 * `error`) while capturing its payload, and ignores any event delivered after
 * a terminal — so the state records exactly one terminal outcome. Pure and
 * never throws.
 */
import type { Citation } from "../domain";
import type { SseFrame } from "./parse";

const TERMINAL_TYPES: ReadonlySet<string> = new Set(["completion", "error"]);

export interface SingleAgentStreamState {
  /** Non-terminal events in received (sequence) order. */
  events: SseFrame[];
  /** The single terminal event, once seen. */
  terminal: SseFrame | null;
  /** True after a terminal event has been recorded. */
  closed: boolean;
  answer?: string;
  citations: Citation[];
  terminationReason?: string;
  errorMessage?: string;
}

export const initialSingleAgentState: SingleAgentStreamState = {
  events: [],
  terminal: null,
  closed: false,
  citations: [],
};

function asCitations(value: unknown): Citation[] {
  if (!Array.isArray(value)) return [];
  const out: Citation[] = [];
  for (const entry of value) {
    if (
      entry &&
      typeof entry === "object" &&
      typeof (entry as Record<string, unknown>).document_id === "string" &&
      typeof (entry as Record<string, unknown>).chunk_id === "string"
    ) {
      const e = entry as Record<string, string>;
      out.push({ document_id: e.document_id, chunk_id: e.chunk_id });
    }
  }
  return out;
}

/** Pure `(state, event) -> state` fold for the single-agent stream. */
export function singleAgentReduce(
  state: SingleAgentStreamState,
  event: SseFrame,
): SingleAgentStreamState {
  // Exactly-one-terminal invariant: once closed, ignore everything.
  if (state.closed) return state;

  if (TERMINAL_TYPES.has(event.type)) {
    const next: SingleAgentStreamState = {
      ...state,
      terminal: event,
      closed: true,
    };
    if (event.type === "completion") {
      const answer = event.data.answer;
      if (typeof answer === "string") next.answer = answer;
      const reason = event.data.termination_reason;
      if (typeof reason === "string") next.terminationReason = reason;
      next.citations = asCitations(event.data.citations);
    } else {
      const message = event.data.message;
      next.errorMessage =
        typeof message === "string" ? message : "The run failed.";
    }
    return next;
  }

  // Non-terminal event: append in received order.
  return { ...state, events: [...state.events, event] };
}
