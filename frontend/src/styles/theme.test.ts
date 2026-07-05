import { describe, it, expect } from "vitest";
import fc from "fast-check";

import {
  resolveToken,
  FALLBACK_TOKEN,
  SEMANTIC_ROLES,
  TOKENS,
  type ThemeName,
} from "./theme";

/**
 * Task 9.1 — property test for total design-token resolution.
 *
 * Feature: agentforge-frontend, Property 13: Design-token resolution is total
 * over theme × semantic role
 *
 * **Validates: Premium UX & Design System §1; supports Requirements 4.1**
 */
describe("Property 13: Design-token resolution is total over theme × semantic role", () => {
  const themes: ThemeName[] = ["dark", "light"];
  const themeArb = fc.constantFrom<ThemeName>("dark", "light");
  const declaredRoleArb = fc.constantFrom(...SEMANTIC_ROLES);

  it("returns a defined, non-empty value for every declared role in either theme", () => {
    fc.assert(
      fc.property(themeArb, declaredRoleArb, (theme, role) => {
        const value = resolveToken(theme, role);
        expect(typeof value).toBe("string");
        expect(value.length).toBeGreaterThan(0);
        // Declared roles resolve to the theme's actual token value (mirror of tokens.css).
        expect(value).toBe(TOKENS[theme][role]);
      }),
      { numRuns: 200 },
    );
  });

  it("returns the single deterministic fallback for undeclared roles, never throwing", () => {
    // Arbitrary strings that are NOT declared semantic roles.
    const undeclaredArb = fc
      .string()
      .filter((s) => !(SEMANTIC_ROLES as readonly string[]).includes(s));

    fc.assert(
      fc.property(themeArb, undeclaredArb, (theme, role) => {
        const first = resolveToken(theme, role);
        const second = resolveToken(theme, role);
        expect(first).toBe(FALLBACK_TOKEN);
        // Deterministic across repeated calls for the same input.
        expect(second).toBe(first);
        expect(first.length).toBeGreaterThan(0);
      }),
      { numRuns: 200 },
    );
  });

  it("never throws for arbitrary theme-ish and role-ish inputs (totality)", () => {
    fc.assert(
      fc.property(fc.string(), fc.string(), (maybeTheme, role) => {
        const theme = (themes as string[]).includes(maybeTheme)
          ? (maybeTheme as ThemeName)
          : "dark";
        expect(() => resolveToken(theme, role)).not.toThrow();
        const value = resolveToken(theme, role);
        expect(value.length).toBeGreaterThan(0);
      }),
      { numRuns: 200 },
    );
  });
});
