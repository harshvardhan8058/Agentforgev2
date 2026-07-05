/**
 * `extractCitations`: the pure inline-citation segmentation (Property 15).
 *
 * Splits a text run into an ordered stream of segments in which every inline
 * `[n]` marker becomes either a **citation** segment (when `n` is in `1..N` and
 * therefore points at a real `Citation`) or **inert text** (when `n` is out of
 * range, or the bracketed token is not a numeric reference). It is **total**:
 * it never throws, never drops an in-range marker, and never turns an
 * out-of-range marker into a link.
 */
import type { Citation } from "../../api/domain";

/** A rendered segment: literal text, or a resolved citation reference. */
export type CitationSegment =
  | { kind: "text"; text: string }
  | {
      kind: "citation";
      /** The literal marker as it appeared, e.g. `"[2]"`. */
      marker: string;
      /** The 1-based citation index (`1..N`). */
      index: number;
      /** The referenced citation. */
      citation: Citation;
    };

/** Matches an inline `[n]` marker with one or more decimal digits. */
const MARKER = /\[(\d+)\]/g;

/**
 * Segment `text` into literal-text and citation runs against `citations`
 * (length `N`). Any `[n]` with `1 <= n <= N` resolves to `citations[n-1]`;
 * anything else is preserved verbatim as inert text.
 */
export function extractCitations(
  text: string,
  citations: readonly Citation[],
): CitationSegment[] {
  const segments: CitationSegment[] = [];
  const n = citations.length;

  // Guard against non-string inputs so the function is genuinely total.
  const source = typeof text === "string" ? text : String(text ?? "");

  let lastIndex = 0;
  // Fresh regex state per call (the shared literal is stateful with /g).
  MARKER.lastIndex = 0;

  let match: RegExpExecArray | null;
  while ((match = MARKER.exec(source)) !== null) {
    const [marker, digits] = match;
    const start = match.index;
    const value = Number.parseInt(digits, 10);
    const inRange = Number.isInteger(value) && value >= 1 && value <= n;

    if (inRange) {
      // Emit any preceding literal text, then the resolved citation.
      if (start > lastIndex) {
        segments.push({ kind: "text", text: source.slice(lastIndex, start) });
      }
      segments.push({
        kind: "citation",
        marker,
        index: value,
        citation: citations[value - 1],
      });
      lastIndex = start + marker.length;
    }
    // Out-of-range markers are left inert: they stay in the text run, so we do
    // not advance `lastIndex` past them (they are flushed with surrounding text).
  }

  // Flush the trailing literal remainder.
  if (lastIndex < source.length) {
    segments.push({ kind: "text", text: source.slice(lastIndex) });
  }

  return segments;
}
