/**
 * A pure line-level diff for comparing two immutable prompt versions.
 *
 * This exists because the prompt studio previously delegated diffing to Monaco,
 * which `@monaco-editor/react` fetches from a CDN at runtime. In a self-hosted
 * deployment the browser cannot reach that CDN, so the editor sat on "Loading…"
 * forever and the prompt body could neither be written nor compared. A diff over
 * a handful of lines does not justify a 70 MB dependency and an outbound network
 * call, so it is computed here instead: deterministic, offline, and testable.
 *
 * The algorithm is a standard longest-common-subsequence walk. Prompt bodies are
 * small, but the DP table is quadratic, so an oversized input degrades to a
 * whole-block replacement rather than allocating an enormous matrix.
 */

/** One line of a rendered diff. */
export interface DiffLine {
  readonly kind: "equal" | "add" | "remove";
  readonly text: string;
  /** 1-based line number on the original side, or null for an addition. */
  readonly leftNumber: number | null;
  /** 1-based line number on the modified side, or null for a removal. */
  readonly rightNumber: number | null;
}

/** Above this many lines on either side, skip the quadratic table. */
const MAX_LINES_FOR_LCS = 1200;

/** Split into lines without inventing a trailing empty line for "". */
function toLines(text: string): string[] {
  return text.length === 0 ? [] : text.split("\n");
}

/** Every original line removed, then every modified line added. */
function wholeBlockReplacement(left: string[], right: string[]): DiffLine[] {
  return [
    ...left.map((text, i) => ({
      kind: "remove" as const,
      text,
      leftNumber: i + 1,
      rightNumber: null,
    })),
    ...right.map((text, i) => ({
      kind: "add" as const,
      text,
      leftNumber: null,
      rightNumber: i + 1,
    })),
  ];
}

/**
 * Diff `original` against `modified`, line by line.
 *
 * Returns the lines in reading order: an unchanged line appears once carrying
 * both numbers, a removal carries only a left number, an addition only a right
 * number. Removals are emitted before additions at the same position so a
 * changed line reads as "was / now".
 */
export function diffLines(original: string, modified: string): DiffLine[] {
  const left = toLines(original);
  const right = toLines(modified);

  if (left.length === 0 && right.length === 0) return [];
  if (left.length > MAX_LINES_FOR_LCS || right.length > MAX_LINES_FOR_LCS) {
    return wholeBlockReplacement(left, right);
  }

  // lcs[i][j] = length of the longest common subsequence of left[i:] and right[j:].
  const lcs: number[][] = Array.from({ length: left.length + 1 }, () =>
    new Array<number>(right.length + 1).fill(0),
  );
  for (let i = left.length - 1; i >= 0; i -= 1) {
    for (let j = right.length - 1; j >= 0; j -= 1) {
      lcs[i][j] =
        left[i] === right[j]
          ? lcs[i + 1][j + 1] + 1
          : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }

  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < left.length && j < right.length) {
    if (left[i] === right[j]) {
      out.push({
        kind: "equal",
        text: left[i],
        leftNumber: i + 1,
        rightNumber: j + 1,
      });
      i += 1;
      j += 1;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      // Dropping the left line keeps at least as much in common: a removal.
      out.push({
        kind: "remove",
        text: left[i],
        leftNumber: i + 1,
        rightNumber: null,
      });
      i += 1;
    } else {
      out.push({ kind: "add", text: right[j], leftNumber: null, rightNumber: j + 1 });
      j += 1;
    }
  }
  while (i < left.length) {
    out.push({ kind: "remove", text: left[i], leftNumber: i + 1, rightNumber: null });
    i += 1;
  }
  while (j < right.length) {
    out.push({ kind: "add", text: right[j], leftNumber: null, rightNumber: j + 1 });
    j += 1;
  }
  return out;
}

/** Counts for a diff summary line. */
export interface DiffStats {
  readonly added: number;
  readonly removed: number;
  readonly unchanged: number;
}

export function diffStats(lines: readonly DiffLine[]): DiffStats {
  let added = 0;
  let removed = 0;
  let unchanged = 0;
  for (const line of lines) {
    if (line.kind === "add") added += 1;
    else if (line.kind === "remove") removed += 1;
    else unchanged += 1;
  }
  return { added, removed, unchanged };
}

/** Matches a `{{ variable }}` placeholder in a prompt body. */
const PLACEHOLDER = /\{\{\s*(\w+)\s*\}\}/g;

/**
 * The distinct variable names a prompt body references, in first-appearance
 * order.
 *
 * Surfaced next to the editor so the declared-variables field can be kept in
 * step with the body: the API rejects a render whose declared set does not cover
 * the body, and previously nothing in the UI revealed that mismatch.
 */
export function referencedVariables(body: string): string[] {
  const seen: string[] = [];
  for (const match of body.matchAll(PLACEHOLDER)) {
    if (!seen.includes(match[1])) seen.push(match[1]);
  }
  return seen;
}
