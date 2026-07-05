import { describe, it, expect } from "vitest";
import fc from "fast-check";

import {
  initialSingleAgentState,
  singleAgentReduce,
} from "./singleAgentReducer";
import type { SseFrame } from "./parse";

const NON_TERMINAL = ["step", "tool_call", "delta"] as const;

const nonTerminalArb: fc.Arbitrary<SseFrame> = fc
  .record({ type: fc.constantFrom(...NON_TERMINAL), seq: fc.nat() })
  .map(({ type, seq }) => ({ type, data: { sequence: seq } }));

const completionArb: fc.Arbitrary<SseFrame> = fc
  .record({ answer: fc.string(), seq: fc.nat() })
  .map(({ answer, seq }) => ({
    type: "completion",
    data: {
      sequence: seq,
      answer,
      termination_reason: "final-answer",
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

describe("api/sse/singleAgentReducer", () => {
  // Feature: agentforge-frontend, Property 8: The single-agent reducer preserves order and closes on exactly one terminal
  it("Property 8: preserves order and closes on exactly one terminal", () => {
    fc.assert(
      fc.property(
        fc.array(nonTerminalArb, { maxLength: 20 }),
        terminalArb,
        fc.array(fc.oneof(nonTerminalArb, terminalArb), { maxLength: 10 }),
        (before, terminal, after) => {
          const all = [...before, terminal, ...after];
          const finalState = all.reduce(singleAgentReduce, initialSingleAgentState);

          // Non-terminal events preserved in received order (only those before
          // the terminal are kept; post-terminal events are ignored).
          expect(finalState.events).toEqual(before);
          // Closed with exactly the first terminal recorded.
          expect(finalState.closed).toBe(true);
          expect(finalState.terminal).toEqual(terminal);

          if (terminal.type === "completion") {
            expect(finalState.answer).toBe(terminal.data.answer);
            expect(finalState.terminationReason).toBe("final-answer");
            expect(finalState.citations).toEqual([
              { document_id: "d1", chunk_id: "c1" },
            ]);
            expect(finalState.errorMessage).toBeUndefined();
          } else {
            expect(finalState.errorMessage).toBe(terminal.data.message);
          }
        },
      ),
      { numRuns: 200 },
    );
  });

  it("ignores events after a terminal (idempotent close)", () => {
    const s1 = singleAgentReduce(initialSingleAgentState, {
      type: "completion",
      data: { sequence: 1, answer: "done", citations: [] },
    });
    const s2 = singleAgentReduce(s1, { type: "delta", data: { sequence: 2 } });
    expect(s2).toBe(s1);
  });
});
