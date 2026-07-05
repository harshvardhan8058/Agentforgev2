/**
 * Pure multi-agent SSE reducer (Property 9).
 *
 * `multiAgentReduce` folds parsed frames into a state that:
 *  - exposes the events ordered by `sequence`,
 *  - buckets agent events (`agent_started`, `plan`, `research`, `draft`,
 *    `critic_feedback`) by their `role_id`,
 *  - records an `approval_required` event as a **non-terminal** pause
 *    (`closed = false`, checkpoint exposed), and
 *  - transitions to `closed` only on the single terminal `completion`
 *    (capturing final output + citations + termination reason) or `error`.
 *
 * Pure and never throws.
 */
import type { Citation } from "../domain";
import type { SseFrame } from "./parse";

const TERMINAL_TYPES: ReadonlySet<string> = new Set(["completion", "error"]);
const AGENT_TYPES: ReadonlySet<string> = new Set([
  "agent_started",
  "plan",
  "research",
  "draft",
  "critic_feedback",
]);

export interface MultiAgentStreamState {
  /** All events ordered by `sequence`. */
  events: SseFrame[];
  /** Agent events bucketed by `role_id`. */
  byRole: Record<string, SseFrame[]>;
  /** A non-terminal approval pause, when awaiting a human decision. */
  approval: { checkpoint: string; runId: string } | null;
  /** The single terminal event, once seen. */
  terminal: SseFrame | null;
  closed: boolean;
  finalAnswer?: string;
  citations: Citation[];
  terminationReason?: string;
  errorMessage?: string;
}

export const initialMultiAgentState: MultiAgentStreamState = {
  events: [],
  byRole: {},
  approval: null,
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

/** Insert `event` into `events` keeping ascending `sequence` order (stable). */
function insertBySequence(events: SseFrame[], event: SseFrame): SseFrame[] {
  const seq = typeof event.data.sequence === "number" ? event.data.sequence : Number.POSITIVE_INFINITY;
  const next = [...events];
  let i = next.length;
  while (i > 0) {
    const prev = next[i - 1];
    const prevSeq =
      typeof prev.data.sequence === "number" ? prev.data.sequence : Number.POSITIVE_INFINITY;
    if (prevSeq <= seq) break;
    i--;
  }
  next.splice(i, 0, event);
  return next;
}

/** Pure `(state, event) -> state` fold for the multi-agent stream. */
export function multiAgentReduce(
  state: MultiAgentStreamState,
  event: SseFrame,
): MultiAgentStreamState {
  // Exactly-one-terminal invariant: once closed, ignore everything.
  if (state.closed) return state;

  const events = insertBySequence(state.events, event);

  // Terminal events close the stream.
  if (TERMINAL_TYPES.has(event.type)) {
    const next: MultiAgentStreamState = {
      ...state,
      events,
      terminal: event,
      closed: true,
      // A terminal supersedes any pending approval pause.
      approval: null,
    };
    if (event.type === "completion") {
      const answer =
        typeof event.data.answer === "string"
          ? event.data.answer
          : typeof event.data.content === "string"
            ? event.data.content
            : undefined;
      if (answer !== undefined) next.finalAnswer = answer;
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

  // approval_required is a NON-terminal pause.
  if (event.type === "approval_required") {
    const checkpoint =
      typeof event.data.checkpoint === "string" ? event.data.checkpoint : "";
    const runId = typeof event.data.run_id === "string" ? event.data.run_id : "";
    return {
      ...state,
      events,
      approval: { checkpoint, runId },
    };
  }

  // Agent events are additionally bucketed by role_id.
  if (AGENT_TYPES.has(event.type) && typeof event.data.role_id === "string") {
    const roleId = event.data.role_id;
    const bucket = state.byRole[roleId] ?? [];
    return {
      ...state,
      events,
      byRole: { ...state.byRole, [roleId]: [...bucket, event] },
    };
  }

  // Any other non-terminal event: just record it in sequence order.
  return { ...state, events };
}
