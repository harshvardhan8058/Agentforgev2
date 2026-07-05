import { describe, it, expect } from "vitest";
import fc from "fast-check";

import {
  buildShortcutRegistry,
  normalizeChord,
  type ShortcutDeclaration,
} from "./useKeyboardShortcuts";

/** Modifier tokens the generator may emit (case is randomized separately). */
const MODIFIER_TOKENS = ["Mod", "Ctrl", "Meta", "Alt", "Shift"] as const;
const KEY_TOKENS = ["k", "p", "d", "j", "/", "?", "enter", "1"] as const;

/** Randomly re-case a token to exercise case-insensitivity. */
function recase(token: string, seed: number): string {
  return token
    .split("")
    .map((ch, i) => ((seed >> i) & 1 ? ch.toUpperCase() : ch.toLowerCase()))
    .join("");
}

/** An arbitrary single-step chord: a subset of modifiers + one key. */
const chordPartsArb = fc.record({
  modifiers: fc.uniqueArray(fc.constantFrom(...MODIFIER_TOKENS), {
    maxLength: MODIFIER_TOKENS.length,
  }),
  key: fc.constantFrom(...KEY_TOKENS),
});

describe("useKeyboardShortcuts — normalization", () => {
  // Feature: agentforge-frontend, Property 14: The keyboard-shortcut registry has no duplicate binding collisions
  it("Property 14 (normalization): case- and modifier-order-insensitive", () => {
    fc.assert(
      fc.property(chordPartsArb, fc.integer(), fc.integer(), (parts, s1, s2) => {
        const { modifiers, key } = parts;

        // Rendering A: given order, given case.
        const chordA = [...modifiers, key].join("+");

        // Rendering B: shuffled modifier order, re-cased tokens.
        const shuffled = [...modifiers].reverse();
        const chordB = [
          ...shuffled.map((m, i) => recase(m, s1 + i)),
          recase(key, s2),
        ].join("+");

        // Both renderings normalize to the exact same canonical chord.
        expect(normalizeChord(chordA)).toBe(normalizeChord(chordB));
      }),
      { numRuns: 200 },
    );
  });
});

describe("useKeyboardShortcuts — registry builder (Property 14)", () => {
  const declArb: fc.Arbitrary<ShortcutDeclaration> = fc.record({
    id: fc.string({ minLength: 1, maxLength: 6 }),
    chord: chordPartsArb.map(({ modifiers, key }) => [...modifiers, key].join("+")),
    label: fc.string(),
    area: fc.constantFrom("Navigation", "Actions", "General"),
  });

  // Feature: agentforge-frontend, Property 14: The keyboard-shortcut registry has no duplicate binding collisions
  it("Property 14: every normalized chord maps to exactly one action; collisions are surfaced, never dropped", () => {
    fc.assert(
      fc.property(fc.array(declArb, { maxLength: 40 }), (declarations) => {
        const registry = buildShortcutRegistry(declarations);

        // Ground truth: group distinct action ids per normalized chord.
        const idsByChord = new Map<string, Set<string>>();
        for (const decl of declarations) {
          const chord = normalizeChord(decl.chord);
          const set = idsByChord.get(chord) ?? new Set<string>();
          set.add(decl.id);
          idsByChord.set(chord, set);
        }

        const collisionChords = new Set(registry.collisions.map((c) => c.chord));

        for (const [chord, ids] of idsByChord) {
          if (ids.size > 1) {
            // Ambiguous chord: surfaced as a collision, excluded from byChord.
            expect(collisionChords.has(chord)).toBe(true);
            expect(registry.byChord.has(chord)).toBe(false);
            const collision = registry.collisions.find((c) => c.chord === chord)!;
            expect(new Set(collision.actionIds)).toEqual(ids);
          } else {
            // Unambiguous chord: bound to exactly one action, no collision.
            expect(registry.byChord.has(chord)).toBe(true);
            expect(collisionChords.has(chord)).toBe(false);
            const bound = registry.byChord.get(chord)!;
            expect(ids.has(bound.id)).toBe(true);
          }
        }

        // byChord never contains a collided chord (no silent overwrite).
        for (const chord of registry.byChord.keys()) {
          expect(collisionChords.has(chord)).toBe(false);
        }
      }),
      { numRuns: 200 },
    );
  });

  it("treats Mod+K and mod+k as the same binding (single action, no collision)", () => {
    const registry = buildShortcutRegistry([
      { id: "a", chord: "Mod+K", label: "Palette", area: "General" },
    ]);
    expect(registry.byChord.get("mod+k")?.id).toBe("a");
    expect(registry.collisions).toHaveLength(0);
  });

  it("surfaces a collision when two distinct actions claim the same chord", () => {
    const registry = buildShortcutRegistry([
      { id: "a", chord: "Mod+K", label: "One", area: "General" },
      { id: "b", chord: "mod+k", label: "Two", area: "General" },
    ]);
    expect(registry.byChord.has("mod+k")).toBe(false);
    expect(registry.collisions).toHaveLength(1);
    expect(new Set(registry.collisions[0].actionIds)).toEqual(new Set(["a", "b"]));
  });
});
