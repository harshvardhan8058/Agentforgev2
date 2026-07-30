import { describe, it, expect } from "vitest";

import { looksLikeDecisionEnvelope, stripDecisionEnvelope } from "./agentText";

/**
 * The render-boundary safety net for leaked decision envelopes.
 *
 * The API is responsible for unwrapping `{"action": "final", "answer": "..."}`
 * and that is where the observed defects were fixed. These tests pin the
 * client-side backstop, whose contract has two halves that are equally
 * important:
 *
 * 1. An envelope that somehow reaches the client is reduced to its prose.
 * 2. Anything that is *not* an envelope is returned byte-identical — including
 *    prose that happens to discuss JSON, which a naive "strip JSON" would
 *    mangle. A safety net that damages normal answers is worse than none.
 */
describe("stripDecisionEnvelope", () => {
  describe("leaves non-envelope text untouched", () => {
    const untouched = [
      ["plain prose", "Cars are assembled on a production line."],
      ["multi-paragraph prose", "First line.\n\nSecond line.\n\nThird."],
      ["markdown", "# Title\n\n- one\n- two\n\n**bold** and `code`."],
      [
        "prose that discusses an action field",
        'Send {"action": "run"} to the endpoint to start it.',
      ],
      ["a fenced code sample", '```json\n{"key": "value"}\n```'],
      ["json that is not a decision", '{"status": "ok", "count": 3}'],
      ["an empty string", ""],
    ] as const;

    for (const [name, text] of untouched) {
      it(name, () => {
        expect(stripDecisionEnvelope(text)).toBe(text);
      });
    }
  });

  describe("unwraps a well-formed envelope", () => {
    it("returns the answer prose", () => {
      expect(
        stripDecisionEnvelope('{"action": "final", "answer": "All done."}'),
      ).toBe("All done.");
    });

    it("resolves escaped newlines", () => {
      expect(
        stripDecisionEnvelope('{"action": "final", "answer": "one\\ntwo"}'),
      ).toBe("one\ntwo");
    });

    it("handles a fenced envelope", () => {
      expect(
        stripDecisionEnvelope('```json\n{"action": "final", "answer": "fenced"}\n```'),
      ).toBe("fenced");
    });
  });

  describe("unwraps the malformed envelope observed in production", () => {
    // Escaped \n, real newlines and stray trailing backslashes together: not
    // parseable as JSON by any parser, which is how it reached the UI verbatim.
    const observed = [
      '{ "action": "final", "answer": "To create a car, follow these steps:\\n',
      "\\n\\",
      "",
      "Plan the car's basic requirements: purpose, target market, and budget\\n",
      "This will determine the overall design and production costs.\\n",
      '\\n\\\n\\nThe engine type will depend on the target market." }',
    ].join("\n");

    it("recovers the prose", () => {
      const out = stripDecisionEnvelope(observed);

      expect(out).toContain("To create a car, follow these steps:");
      expect(out).toContain("target market, and budget");
    });

    it("does not show the envelope keys", () => {
      const out = stripDecisionEnvelope(observed);

      expect(out).not.toContain('"action"');
      expect(out).not.toContain('"answer"');
      expect(out.trimStart().startsWith("{")).toBe(false);
    });

    it("leaves no escape artefacts behind", () => {
      const out = stripDecisionEnvelope(observed);

      expect(out).not.toContain("\\n");
      expect(out).not.toContain("\\");
      expect(out).not.toContain("\n\n\n");
    });
  });

  describe("degrades safely", () => {
    it("keeps the original when an envelope carries no recoverable prose", () => {
      // Better an imperfect string than an empty answer card with no explanation.
      const bare = '{"action": "order", "steps": [,]}';

      expect(stripDecisionEnvelope(bare)).toBe(bare);
    });

    it("recovers prose from an envelope with an unrecognized action", () => {
      const out = stripDecisionEnvelope(
        '{"action": "order", "answer": "Do this first."}',
      );

      expect(out).toBe("Do this first.");
    });
  });
});

describe("looksLikeDecisionEnvelope", () => {
  it.each([
    ['{"action": "final", "answer": "x"}', true],
    ['{"action":"tool","tool":"rag_search"}', true],
    ['```json\n{"action": "order"}\n```', true],
    ["Plain prose about an action.", false],
    ['{"status": "ok"}', false],
    ['Use {"action": "final"} in the body.', false],
    ["", false],
  ])("%s -> %s", (text, expected) => {
    expect(looksLikeDecisionEnvelope(text)).toBe(expected);
  });
});
