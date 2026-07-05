import { describe, it, expect } from "vitest";
import fc from "fast-check";

import { parseSseFrame, renderSseFrame } from "./parse";

// A JSON-object payload carrying a monotonic `sequence`, plus arbitrary fields.
const dataArb = fc
  .record({
    sequence: fc.nat(),
    role_id: fc.option(fc.string(), { nil: undefined }),
    content: fc.option(fc.string(), { nil: undefined }),
    answer: fc.option(fc.string(), { nil: undefined }),
  })
  .map((r) => {
    const out: Record<string, unknown> = { sequence: r.sequence };
    if (r.role_id !== undefined) out.role_id = r.role_id;
    if (r.content !== undefined) out.content = r.content;
    if (r.answer !== undefined) out.answer = r.answer;
    return out;
  });

const typeArb = fc.constantFrom(
  "step",
  "tool_call",
  "delta",
  "completion",
  "error",
  "agent_started",
  "plan",
  "research",
  "draft",
  "critic_feedback",
  "approval_required",
);

describe("api/sse/parse — parseSseFrame", () => {
  // Feature: agentforge-frontend, Property 10: SSE frame parsing round-trips the backend frame format
  it("Property 10: SSE frame parsing round-trips the backend frame format", () => {
    fc.assert(
      fc.property(typeArb, dataArb, (type, data) => {
        const raw = renderSseFrame(type, data);
        const frame = parseSseFrame(raw);
        expect(frame).not.toBeNull();
        expect(frame!.type).toBe(type);
        expect(frame!.data).toEqual(data);
      }),
      { numRuns: 200 },
    );
  });

  it("is total over arbitrary strings (never throws)", () => {
    fc.assert(
      fc.property(fc.string(), (s) => {
        expect(() => parseSseFrame(s)).not.toThrow();
      }),
      { numRuns: 200 },
    );
  });

  it("returns null for unparseable frames", () => {
    expect(parseSseFrame("garbage")).toBeNull();
    expect(parseSseFrame("event: step\n")).toBeNull(); // no data
    expect(parseSseFrame("data: {}\n\n")).toBeNull(); // no event
    expect(parseSseFrame("event: step\ndata: not-json\n\n")).toBeNull();
    expect(parseSseFrame("event: step\ndata: 42\n\n")).toBeNull(); // not an object
    expect(parseSseFrame(123 as unknown as string)).toBeNull();
  });
});
