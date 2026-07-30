import { describe, it, expect } from "vitest";

import { describeGuardrail } from "./guardrailCatalog";

/**
 * Descriptions are keyed on the guardrail's stable API `name`, not on the
 * `kind`, which is `type(guardrail).__name__` and therefore free to change with
 * any refactor.
 */
describe("describeGuardrail", () => {
  it.each([
    ["non_empty", "Non-empty content"],
    ["max_length", "Maximum length"],
    ["blocklist", "Term blocklist"],
  ])("labels the built-in %s guardrail", (name, label) => {
    expect(describeGuardrail(name).label).toBe(label);
  });

  it.each(["non_empty", "max_length", "blocklist"])(
    "describes what %s enforces",
    (name) => {
      const description = describeGuardrail(name).description;
      expect(description).not.toBeNull();
      expect((description as string).length).toBeGreaterThan(20);
    },
  );

  it("does not quote a concrete limit it cannot know", () => {
    // The config endpoint returns no configured values, so naming a number here
    // could contradict the deployment.
    expect(describeGuardrail("max_length").description).not.toMatch(/\d/);
  });

  it("humanises an unknown guardrail name", () => {
    expect(describeGuardrail("custom_policy_check").label).toBe(
      "Custom policy check",
    );
  });

  it("gives an unknown guardrail no description rather than guessing", () => {
    expect(describeGuardrail("custom_policy_check").description).toBeNull();
  });

  it("falls back to the raw name when it cannot be humanised", () => {
    expect(describeGuardrail("_").label).toBe("_");
  });
});
