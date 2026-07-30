import { describe, it, expect } from "vitest";
import fc from "fast-check";

import {
  diffLines,
  diffStats,
  referencedVariables,
  type DiffLine,
} from "./lineDiff";

/**
 * The line diff that replaced Monaco's diff editor.
 *
 * Monaco was fetched from a CDN, so on a self-hosted deployment version
 * comparison never rendered at all. Owning the diff means owning its
 * correctness, so the invariant that matters is asserted as a property: the
 * non-added lines must reconstruct the original exactly, and the non-removed
 * lines must reconstruct the modified text exactly. A diff that loses or invents
 * a line would silently misrepresent what changed between two immutable
 * versions.
 */

/** Rebuild the original side from a diff (everything except additions). */
function leftOf(lines: readonly DiffLine[]): string[] {
  return lines.filter((l) => l.kind !== "add").map((l) => l.text);
}

/** Rebuild the modified side from a diff (everything except removals). */
function rightOf(lines: readonly DiffLine[]): string[] {
  return lines.filter((l) => l.kind !== "remove").map((l) => l.text);
}

function toLines(text: string): string[] {
  return text.length === 0 ? [] : text.split("\n");
}

describe("diffLines", () => {
  it("reports no changes for identical text", () => {
    const lines = diffLines("a\nb\nc", "a\nb\nc");

    expect(lines.every((l) => l.kind === "equal")).toBe(true);
    expect(diffStats(lines)).toEqual({ added: 0, removed: 0, unchanged: 3 });
  });

  it("returns an empty diff for two empty bodies", () => {
    expect(diffLines("", "")).toEqual([]);
  });

  it("detects a pure insertion", () => {
    const lines = diffLines("a\nc", "a\nb\nc");

    expect(diffStats(lines)).toEqual({ added: 1, removed: 0, unchanged: 2 });
    const added = lines.find((l) => l.kind === "add");
    expect(added?.text).toBe("b");
    expect(added?.leftNumber).toBeNull();
    expect(added?.rightNumber).toBe(2);
  });

  it("detects a pure deletion", () => {
    const lines = diffLines("a\nb\nc", "a\nc");

    expect(diffStats(lines)).toEqual({ added: 0, removed: 1, unchanged: 2 });
    const removed = lines.find((l) => l.kind === "remove");
    expect(removed?.text).toBe("b");
    expect(removed?.leftNumber).toBe(2);
    expect(removed?.rightNumber).toBeNull();
  });

  it("renders a changed line as a removal followed by an addition", () => {
    const lines = diffLines("a\nold\nc", "a\nnew\nc");

    const kinds = lines.map((l) => l.kind);
    expect(kinds).toEqual(["equal", "remove", "add", "equal"]);
  });

  it("treats an all-new body as additions only", () => {
    const lines = diffLines("", "a\nb");

    expect(diffStats(lines)).toEqual({ added: 2, removed: 0, unchanged: 0 });
  });

  it("treats an emptied body as removals only", () => {
    const lines = diffLines("a\nb", "");

    expect(diffStats(lines)).toEqual({ added: 0, removed: 2, unchanged: 0 });
  });

  it("preserves blank lines rather than collapsing them", () => {
    // A prompt's paragraph breaks are meaningful; dropping them would show a
    // diff that does not match the stored body.
    const lines = diffLines("a\n\nb", "a\n\nb");

    expect(lines).toHaveLength(3);
    expect(lines[1].text).toBe("");
  });

  it("numbers both sides consistently", () => {
    const lines = diffLines("a\nb", "a\nx\nb");

    for (const line of lines) {
      if (line.kind === "add") expect(line.leftNumber).toBeNull();
      if (line.kind === "remove") expect(line.rightNumber).toBeNull();
      if (line.kind === "equal") {
        expect(line.leftNumber).not.toBeNull();
        expect(line.rightNumber).not.toBeNull();
      }
    }
  });

  it("degrades to a whole-block replacement beyond the LCS size cap", () => {
    // Guards the quadratic table: a pathological body must not allocate an
    // enormous matrix.
    const big = Array.from({ length: 1300 }, (_, i) => `line ${i}`).join("\n");
    const lines = diffLines(big, `${big}\nextra`);

    expect(lines.every((l) => l.kind !== "equal")).toBe(true);
    expect(diffStats(lines).unchanged).toBe(0);
  });

  describe("property: a diff never loses or invents a line", () => {
    const body = fc
      .array(fc.string({ maxLength: 12 }), { maxLength: 25 })
      .map((lines) => lines.join("\n"));

    it("the non-added lines reconstruct the original", () => {
      fc.assert(
        fc.property(body, body, (original, modified) => {
          expect(leftOf(diffLines(original, modified))).toEqual(toLines(original));
        }),
        { numRuns: 300 },
      );
    });

    it("the non-removed lines reconstruct the modified text", () => {
      fc.assert(
        fc.property(body, body, (original, modified) => {
          expect(rightOf(diffLines(original, modified))).toEqual(toLines(modified));
        }),
        { numRuns: 300 },
      );
    });

    it("identical inputs always diff to all-equal", () => {
      fc.assert(
        fc.property(body, (text) => {
          const stats = diffStats(diffLines(text, text));
          expect(stats.added).toBe(0);
          expect(stats.removed).toBe(0);
        }),
        { numRuns: 200 },
      );
    });
  });
});

describe("referencedVariables", () => {
  it("finds each placeholder once, in first-appearance order", () => {
    expect(referencedVariables("{{b}} then {{a}} then {{b}}")).toEqual(["b", "a"]);
  });

  it("tolerates inner whitespace", () => {
    expect(referencedVariables("{{  name  }}")).toEqual(["name"]);
  });

  it("returns nothing for a body with no placeholders", () => {
    expect(referencedVariables("plain prose")).toEqual([]);
  });

  it("ignores a single-brace token", () => {
    // `{name}` is not the platform's placeholder syntax.
    expect(referencedVariables("{name}")).toEqual([]);
  });
});
