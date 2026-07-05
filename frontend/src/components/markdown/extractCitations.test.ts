import { describe, it, expect } from "vitest";
import fc from "fast-check";

import { extractCitations } from "./extractCitations";
import type { Citation } from "../../api/domain";

const citationArb: fc.Arbitrary<Citation> = fc.record({
  document_id: fc.string({ minLength: 1, maxLength: 8 }),
  chunk_id: fc.string({ minLength: 1, maxLength: 8 }),
});

/** Reassemble the visible text from a segment stream. */
function joinSegments(text: string, citations: readonly Citation[]): string {
  return extractCitations(text, citations)
    .map((s) => (s.kind === "text" ? s.text : s.marker))
    .join("");
}

describe("extractCitations (Property 15)", () => {
  // Feature: agentforge-frontend, Property 15: Markdown citation extraction maps every marker to a valid citation or renders it inert
  it("Property 15: maps every marker to a valid citation or renders it inert; total and lossless", () => {
    fc.assert(
      fc.property(
        fc.array(citationArb, { maxLength: 6 }),
        // Interleave arbitrary prose with arbitrary [n] markers (in and out of range).
        fc.array(
          fc.oneof(
            fc.string().filter((s) => !/[[\]]/.test(s)),
            fc.integer({ min: 0, max: 12 }).map((n) => `[${n}]`),
          ),
          { maxLength: 20 },
        ),
        (citations, tokens) => {
          const text = tokens.join(" ");
          const n = citations.length;

          // Total: never throws.
          const segments = extractCitations(text, citations);

          for (const seg of segments) {
            if (seg.kind === "citation") {
              // Every emitted citation is in range and points at the match.
              expect(seg.index).toBeGreaterThanOrEqual(1);
              expect(seg.index).toBeLessThanOrEqual(n);
              expect(seg.citation).toBe(citations[seg.index - 1]);
            }
          }

          // Count in-range markers present in the source.
          let expectedInRange = 0;
          const re = /\[(\d+)\]/g;
          let m: RegExpExecArray | null;
          while ((m = re.exec(text)) !== null) {
            const v = Number.parseInt(m[1], 10);
            if (v >= 1 && v <= n) expectedInRange += 1;
          }
          const emittedCitations = segments.filter((s) => s.kind === "citation").length;

          // No in-range marker dropped; no out-of-range marker linked.
          expect(emittedCitations).toBe(expectedInRange);

          // Lossless: reassembled visible text equals the original.
          expect(joinSegments(text, citations)).toBe(text);
        },
      ),
      { numRuns: 200 },
    );
  });

  it("links an in-range marker and leaves an out-of-range marker inert", () => {
    const citations: Citation[] = [
      { document_id: "doc-1", chunk_id: "c-1" },
      { document_id: "doc-2", chunk_id: "c-2" },
    ];
    const segments = extractCitations("See [1] and [5] here.", citations);
    const cites = segments.filter((s) => s.kind === "citation");
    expect(cites).toHaveLength(1);
    expect(cites[0].kind === "citation" && cites[0].index).toBe(1);
    // The out-of-range [5] survives as inert text.
    expect(joinSegments("See [1] and [5] here.", citations)).toContain("[5]");
  });

  it("is total for non-reference brackets and empty citation lists", () => {
    expect(() => extractCitations("[abc] [0] [] text", [])).not.toThrow();
    const segments = extractCitations("[1] alpha", []);
    expect(segments.every((s) => s.kind === "text")).toBe(true);
  });
});
