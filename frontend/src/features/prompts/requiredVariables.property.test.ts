import { describe, it, expect } from "vitest";
import fc from "fast-check";

import { missingVariables, canRender } from "./requiredVariables";

/**
 * Task 23.1 — Property 12: Required-variable validation blocks render on
 * exactly the missing set.
 * _Validates: Requirements 12.6_
 *
 * For any declared-variable set × any supplied map, the form blocks submission
 * iff at least one declared variable is unsupplied, and the prompted-for set is
 * exactly the declared variables (de-duplicated, in order) that were not
 * supplied. The expected missing set is computed independently of the
 * implementation from the same definition of "supplied" (present with a
 * non-empty trimmed value).
 */

const NAME_POOL = ["a", "b", "c", "d", "name", "topic", "tone"] as const;
const nameArb = fc.constantFrom(...NAME_POOL);
const declaredArb = fc.array(nameArb, { maxLength: NAME_POOL.length });
const valueArb = fc.oneof(fc.constant(""), fc.constant("   "), fc.string({ minLength: 1 }));
const suppliedArb = fc.dictionary(nameArb, valueArb);

describe("required-variable validation (Property 12)", () => {
  // Feature: agentforge-frontend, Property 12: Required-variable validation blocks render on exactly the missing set
  it("Property 12: blocks iff a declared variable is unsupplied, prompting for exactly the missing set", () => {
    fc.assert(
      fc.property(declaredArb, suppliedArb, (declared, supplied) => {
        // Independent ground truth for "unsupplied": absent or empty/whitespace.
        const expectedMissing: string[] = [];
        const seen = new Set<string>();
        for (const name of declared) {
          if (seen.has(name)) continue;
          seen.add(name);
          const value = supplied[name];
          if (typeof value !== "string" || value.trim().length === 0) {
            expectedMissing.push(name);
          }
        }

        const missing = missingVariables(declared, supplied);
        expect(missing).toEqual(expectedMissing);
        // No duplicates in the prompted-for set.
        expect(new Set(missing).size).toBe(missing.length);
        // Blocking is exactly the "any missing" condition.
        expect(canRender(declared, supplied)).toBe(expectedMissing.length === 0);
      }),
      { numRuns: 200 },
    );
  });
});
