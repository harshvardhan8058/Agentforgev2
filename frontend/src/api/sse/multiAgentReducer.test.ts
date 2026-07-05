import { describe, it, expect } from "vitest";
import fc from "fast-check";

import {
  initialMultiAgentState,
  multiAgentReduce,
} from "./multiAgentReducer";
import type { SseFrame } from "./parse";

const AGENT_TYPES = [
  "agent_started",
  "plan",
  "research",
  "draft",
  "critic_feedback",
] as const;
const ROLES = ["planner", "researcher", "writer", "critic"] as const;

const agentArb: fc.Arbitrary<SseFrame> = fc
  .record({
    type: fc.constantFrom(...AGENT_TYPES),
    role_id: fc.constantFrom(...ROLES),
    seq: fc.nat(),
  })
  .map(({ type, role_id, seq }) => ({ type, data: { sequence: seq, role_id } }));

const approvalArb: fc.Arbitrary<SseFrame> = fc
  .record({ checkpoint: fc.string(), run_id: fc.string(), seq: fc.nat() })
  .map(({ checkpoint, run_id, seq }) => ({
    type: "approval_required",
    data: { sequence: seq, checkpoint, run_id },
  }));

const completionArb: fc.Arbitrary<SseFrame> = fc
  .record({ content: fc.string(), seq: fc.nat() })
  .map(({ content, seq }) => ({
    type: "completion",
    data: {
      sequence: seq,
      content,
      termination_reason: "completed",
      citations: [{ document_id: "d1", chunk_id: "c1" }],
    },
  }));

const errorArb: fc.Arbitrary<SseFrame> = fc
  .record({ message: fc.string({ minLength: 1 }), seq: fc.nat() })
  .map(({ message, seq }) => ({
    type: "error",
    data: { sequence: seq, message, error_type: "provider" },
  }));

const terminalArb = fc.oneof(completionArb, errorArb);

function seqOf(f: SseFrame): number {
  return f.data.sequence as number;
}

describe("api/sse/multiAgentReducer", () => {
  // Feature: agentforge-frontend, Property 9: The multi-agent reducer orders by sequence, attributes roles, and treats approval as non-terminal
  it("Property 9: orders by sequence, attributes roles, treats approval as non-terminal", () => {
    fc.assert(
      fc.property(
        fc.array(fc.oneof(agentArb, approvalArb), { maxLength: 25 }),
        terminalArb,
        (nonTerminal, terminal) => {
          const all = [...nonTerminal, terminal];
          const state = all.reduce(multiAgentReduce, initialMultiAgentState);

          // Events ordered by sequence (non-decreasing).
          for (let i = 1; i < state.events.length; i++) {
            expect(seqOf(state.events[i - 1])).toBeLessThanOrEqual(
              seqOf(state.events[i]),
            );
          }

          // Every agent event is attributed to its role_id bucket.
          const expectedByRole: Record<string, number> = {};
          for (const e of nonTerminal) {
            if (AGENT_TYPES.includes(e.type as (typeof AGENT_TYPES)[number])) {
              const rid = e.data.role_id as string;
              expectedByRole[rid] = (expectedByRole[rid] ?? 0) + 1;
            }
          }
          for (const [rid, count] of Object.entries(expectedByRole)) {
            expect(state.byRole[rid]?.length ?? 0).toBe(count);
          }

          // Closed exactly on the terminal; approval cleared by terminal.
          expect(state.closed).toBe(true);
          expect(state.terminal).toEqual(terminal);
          expect(state.approval).toBeNull();

          if (terminal.type === "completion") {
            expect(state.finalAnswer).toBe(terminal.data.content);
            expect(state.terminationReason).toBe("completed");
            expect(state.citations).toEqual([
              { document_id: "d1", chunk_id: "c1" },
            ]);
          } else {
            expect(state.errorMessage).toBe(terminal.data.message);
          }
        },
      ),
      { numRuns: 200 },
    );
  });

  it("treats approval_required as a non-terminal pause", () => {
    fc.assert(
      fc.property(
        fc.array(agentArb, { maxLength: 10 }),
        approvalArb,
        (agents, approval) => {
          const state = [...agents, approval].reduce(
            multiAgentReduce,
            initialMultiAgentState,
          );
          expect(state.closed).toBe(false);
          expect(state.approval).not.toBeNull();
          expect(state.approval!.checkpoint).toBe(approval.data.checkpoint);
          expect(state.approval!.runId).toBe(approval.data.run_id);
        },
      ),
      { numRuns: 200 },
    );
  });

  it("ignores events after a terminal", () => {
    const s1 = multiAgentReduce(initialMultiAgentState, {
      type: "completion",
      data: { sequence: 1, content: "done", citations: [] },
    });
    const s2 = multiAgentReduce(s1, {
      type: "plan",
      data: { sequence: 2, role_id: "planner" },
    });
    expect(s2).toBe(s1);
  });
});
