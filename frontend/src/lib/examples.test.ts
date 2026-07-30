import { describe, it, expect } from "vitest";

import {
  AGENT_EXAMPLES,
  APPROVAL_EDIT_EXAMPLES,
  APPROVAL_REJECT_EXAMPLES,
  DATASET_NAME_EXAMPLES,
  EVALUATOR_EXAMPLES,
  GUARDRAIL_EXAMPLES,
  MEMBER_EMAIL_EXAMPLES,
  MULTI_AGENT_EXAMPLES,
  PROMPT_STARTERS,
  QUERY_EXAMPLES,
  SAMPLE_DOCUMENTS,
  TEAM_NAME_EXAMPLES,
  suggestVariableValue,
  type Example,
} from "./examples";

/**
 * The preset catalogue.
 *
 * These presets are promises to the Operator: clicking one must produce a
 * working request. So the assertions here are about *validity against the
 * backend*, not about wording — an evaluator name that isn't registered, or a
 * "blocked" example that doesn't actually trip a guardrail, would teach someone
 * the product is broken.
 */

const ALL_EXAMPLE_SETS: ReadonlyArray<readonly [string, readonly Example[]]> = [
  ["QUERY_EXAMPLES", QUERY_EXAMPLES],
  ["AGENT_EXAMPLES", AGENT_EXAMPLES],
  ["MULTI_AGENT_EXAMPLES", MULTI_AGENT_EXAMPLES],
  ["GUARDRAIL_EXAMPLES", GUARDRAIL_EXAMPLES],
  ["DATASET_NAME_EXAMPLES", DATASET_NAME_EXAMPLES],
  ["EVALUATOR_EXAMPLES", EVALUATOR_EXAMPLES],
  ["MEMBER_EMAIL_EXAMPLES", MEMBER_EMAIL_EXAMPLES],
  ["TEAM_NAME_EXAMPLES", TEAM_NAME_EXAMPLES],
  ["APPROVAL_REJECT_EXAMPLES", APPROVAL_REJECT_EXAMPLES],
  ["APPROVAL_EDIT_EXAMPLES", APPROVAL_EDIT_EXAMPLES],
];

describe("every example set", () => {
  it.each(ALL_EXAMPLE_SETS)("%s is non-empty", (_name, examples) => {
    expect(examples.length).toBeGreaterThan(0);
  });

  it.each(ALL_EXAMPLE_SETS)("%s has unique chip labels", (_name, examples) => {
    // The label is the React key in ExampleChips, so duplicates would warn and
    // make selection ambiguous.
    const labels = examples.map((e) => e.label);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it.each(ALL_EXAMPLE_SETS)("%s has short, scannable labels", (_name, examples) => {
    // The whole point of the label/value split is that chips stay compact.
    for (const example of examples) {
      expect(example.label.length).toBeLessThanOrEqual(24);
    }
  });

  it.each(ALL_EXAMPLE_SETS)("%s has a non-empty value", (name, examples) => {
    for (const example of examples) {
      // The guardrail set intentionally includes a whitespace-only value to
      // trip the non_empty guardrail; every other value must carry content.
      if (name === "GUARDRAIL_EXAMPLES") {
        expect(example.value.length).toBeGreaterThan(0);
      } else {
        expect(example.value.trim().length).toBeGreaterThan(0);
      }
    }
  });
});

describe("GUARDRAIL_EXAMPLES", () => {
  it("offers an input that the non_empty guardrail blocks", () => {
    const empty = GUARDRAIL_EXAMPLES.find((e) => e.label.includes("empty"));

    expect(empty).toBeDefined();
    // The server-side check is `content.strip() == ""`.
    expect(empty?.value.trim()).toBe("");
  });

  it("offers an input that exceeds the default max-length guardrail", () => {
    // `guardrail_max_input_chars` defaults to 8000; the check is `len > max`.
    const long = GUARDRAIL_EXAMPLES.find((e) => e.label.includes("long"));

    expect(long).toBeDefined();
    expect((long as Example).value.length).toBeGreaterThan(8000);
  });

  it("offers an input that passes every default guardrail", () => {
    const allowed = GUARDRAIL_EXAMPLES.find((e) => e.label === "Allowed");

    expect(allowed).toBeDefined();
    expect((allowed as Example).value.trim().length).toBeGreaterThan(0);
    expect((allowed as Example).value.length).toBeLessThanOrEqual(8000);
  });
});

describe("EVALUATOR_EXAMPLES", () => {
  // The three deterministic evaluators registered by build_default_evaluators().
  const REGISTERED = ["exact_match", "contains", "heuristic"];

  it("only names evaluators the platform registers", () => {
    for (const example of EVALUATOR_EXAMPLES) {
      const names = example.value.split(",").map((n) => n.trim());
      for (const name of names) {
        expect(REGISTERED).toContain(name);
      }
    }
  });

  it("offers each registered evaluator individually", () => {
    for (const name of REGISTERED) {
      expect(EVALUATOR_EXAMPLES.some((e) => e.value === name)).toBe(true);
    }
  });

  it("parses to the exact list the form submits", () => {
    // The form splits on "," and trims, so a preset must survive that intact.
    const all = EVALUATOR_EXAMPLES.find((e) => e.label === "All three");
    const parsed = (all as Example).value
      .split(",")
      .map((e) => e.trim())
      .filter((e) => e.length > 0);

    expect(parsed).toEqual(REGISTERED);
  });
});

describe("PROMPT_STARTERS", () => {
  it("declares every variable its body references", () => {
    // A starter that referenced an undeclared variable would render with the
    // placeholder left in place.
    for (const starter of PROMPT_STARTERS) {
      const declared = starter.variables.split(",").map((v) => v.trim());
      const referenced = [...starter.body.matchAll(/\{\{\s*(\w+)\s*\}\}/g)].map(
        (m) => m[1],
      );
      for (const name of referenced) {
        expect(declared).toContain(name);
      }
    }
  });

  it("references every variable it declares", () => {
    // The converse: a declared-but-unused variable blocks rendering for nothing.
    for (const starter of PROMPT_STARTERS) {
      const declared = starter.variables.split(",").map((v) => v.trim());
      for (const name of declared) {
        expect(starter.body).toContain(`{{${name}}}`);
      }
    }
  });

  it("has a suggested value for every variable it declares", () => {
    // Otherwise "Fill example values" would leave the form still blocked.
    for (const starter of PROMPT_STARTERS) {
      for (const name of starter.variables.split(",").map((v) => v.trim())) {
        expect(suggestVariableValue(name)).not.toBeNull();
      }
    }
  });

  it("uses unique names and labels", () => {
    const names = PROMPT_STARTERS.map((s) => s.name);
    const labels = PROMPT_STARTERS.map((s) => s.label);

    expect(new Set(names).size).toBe(names.length);
    expect(new Set(labels).size).toBe(labels.length);
  });
});

describe("suggestVariableValue", () => {
  it("is case- and whitespace-insensitive", () => {
    expect(suggestVariableValue("  QUESTION ")).toBe(
      suggestVariableValue("question"),
    );
  });

  it("returns null for an unknown variable rather than guessing", () => {
    // A wrong suggestion in a render preview is worse than no suggestion.
    expect(suggestVariableValue("wibble_factor")).toBeNull();
  });
});

describe("SAMPLE_DOCUMENTS", () => {
  it("provides a small, non-empty corpus", () => {
    expect(SAMPLE_DOCUMENTS.length).toBeGreaterThan(0);
    for (const doc of SAMPLE_DOCUMENTS) {
      expect(doc.content.trim().length).toBeGreaterThan(200);
      expect(doc.summary.trim().length).toBeGreaterThan(0);
    }
  });

  it("uses unique filenames", () => {
    const names = SAMPLE_DOCUMENTS.map((d) => d.filename);
    expect(new Set(names).size).toBe(names.length);
  });

  it("stays well under the default max-length guardrail per document", () => {
    for (const doc of SAMPLE_DOCUMENTS) {
      expect(doc.content.length).toBeLessThan(8000);
    }
  });

  it("contains the material the retrieval examples ask about", () => {
    // This is the coupling that makes the demo coherent: load the corpus, pick
    // any query example, get a grounded answer instead of "no relevant context".
    const corpus = SAMPLE_DOCUMENTS.map((d) => d.content.toLowerCase()).join("\n");

    expect(corpus).toContain("probation");
    expect(corpus).toContain("root cause");
    expect(corpus).toContain("laptop");
    expect(corpus).toContain("risk");
  });
});
