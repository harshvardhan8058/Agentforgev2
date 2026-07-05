/**
 * `useKeyboardShortcuts`: the keyboard-shortcut registry + normalization +
 * collision validation (Property 14), plus a React hook that binds the built
 * registry to the window and exposes it (and its collisions) for the `?`
 * shortcuts overlay.
 *
 * The **registry builder is pure**: for any list of shortcut declarations it
 * normalizes each key-chord (case- and modifier-order-insensitive, e.g.
 * `Mod+K` ≡ `mod+k`) and produces a registry in which every normalized chord
 * maps to **exactly one** action. Whenever two distinct actions declare the
 * same normalized chord it surfaces a **collision** rather than silently
 * overwriting or dropping a binding — so resolving any registered chord yields
 * a unique, unambiguous action.
 */
import { useEffect, useMemo } from "react";

/** A single shortcut declaration supplied by a feature/provider. */
export interface ShortcutDeclaration {
  /** Stable action identifier (distinct actions have distinct ids). */
  id: string;
  /** The key-chord, e.g. `"Mod+K"`, `"?"`, `"g then d"`. */
  chord: string;
  /** Human-readable label shown in the shortcuts overlay. */
  label: string;
  /** Grouping area for the overlay (e.g. "Navigation", "Actions"). */
  area: string;
  /** Optional handler invoked when the chord is pressed. */
  run?: () => void;
}

/** A resolved binding: a normalized chord bound to exactly one declaration. */
export interface ResolvedShortcut extends ShortcutDeclaration {
  /** The normalized chord this action is bound to. */
  normalized: string;
}

/** A collision: one normalized chord claimed by two or more distinct actions. */
export interface ShortcutCollision {
  /** The normalized chord that is ambiguously bound. */
  chord: string;
  /** The distinct action ids competing for the chord (declaration order). */
  actionIds: string[];
}

/** The built registry: unambiguous bindings + any surfaced collisions. */
export interface ShortcutRegistry {
  /** Normalized chord → the single action bound to it (collisions excluded). */
  readonly byChord: ReadonlyMap<string, ResolvedShortcut>;
  /** Every unambiguously-bound shortcut (declaration order preserved). */
  readonly shortcuts: readonly ResolvedShortcut[];
  /** Chords claimed by more than one distinct action — never silently dropped. */
  readonly collisions: readonly ShortcutCollision[];
}

/** Modifier tokens recognized in a chord step (before canonicalization). */
const MODIFIER_ALIASES: Readonly<Record<string, string>> = {
  mod: "mod",
  ctrl: "ctrl",
  control: "ctrl",
  cmd: "meta",
  command: "meta",
  meta: "meta",
  win: "meta",
  super: "meta",
  alt: "alt",
  option: "alt",
  opt: "alt",
  shift: "shift",
};

/** Canonical modifier order so `Shift+Mod` and `mod+shift` collapse together. */
const MODIFIER_RANK: Readonly<Record<string, number>> = {
  mod: 0,
  meta: 1,
  ctrl: 2,
  alt: 3,
  shift: 4,
};

/** Normalize a single chord step (a `+`-joined modifier/key combination). */
function normalizeStep(step: string): string {
  const tokens = step
    .split("+")
    .map((t) => t.trim().toLowerCase())
    .filter((t) => t.length > 0);

  const modifiers = new Set<string>();
  const keys: string[] = [];
  for (const token of tokens) {
    const alias = MODIFIER_ALIASES[token];
    if (alias !== undefined) {
      modifiers.add(alias);
    } else {
      keys.push(token);
    }
  }

  const orderedModifiers = Array.from(modifiers).sort(
    (a, b) => (MODIFIER_RANK[a] ?? 99) - (MODIFIER_RANK[b] ?? 99),
  );
  // Keys keep their given order (multi-key steps are unusual but preserved).
  return [...orderedModifiers, ...keys].join("+");
}

/**
 * Normalize a key-chord to a canonical form: case-insensitive, modifier-order
 * insensitive, and stable across sequence steps (`a then b`). Pure and total.
 */
export function normalizeChord(chord: string): string {
  return chord
    .trim()
    .toLowerCase()
    .split(/\s+then\s+/)
    .map((step) => normalizeStep(step))
    .filter((step) => step.length > 0)
    .join(" then ");
}

/**
 * Build a shortcut registry from a list of declarations (pure, Property 14).
 *
 * Groups declarations by normalized chord; a chord claimed by a single distinct
 * action becomes an unambiguous binding, while a chord claimed by two or more
 * **distinct** action ids is surfaced as a collision and excluded from
 * `byChord` (never silently overwritten or dropped).
 */
export function buildShortcutRegistry(
  declarations: readonly ShortcutDeclaration[],
): ShortcutRegistry {
  // Preserve declaration order while grouping by normalized chord.
  const groups = new Map<string, ResolvedShortcut[]>();
  for (const decl of declarations) {
    const normalized = normalizeChord(decl.chord);
    const resolved: ResolvedShortcut = { ...decl, normalized };
    const bucket = groups.get(normalized);
    if (bucket) {
      bucket.push(resolved);
    } else {
      groups.set(normalized, [resolved]);
    }
  }

  const byChord = new Map<string, ResolvedShortcut>();
  const shortcuts: ResolvedShortcut[] = [];
  const collisions: ShortcutCollision[] = [];

  for (const [normalized, bucket] of groups) {
    const distinctIds = Array.from(new Set(bucket.map((s) => s.id)));
    if (distinctIds.length > 1) {
      // Two or more distinct actions want the same chord — surface it.
      collisions.push({ chord: normalized, actionIds: distinctIds });
    } else {
      // Exactly one distinct action (possibly declared once); bind it.
      const [only] = bucket;
      byChord.set(normalized, only);
      shortcuts.push(only);
    }
  }

  return { byChord, shortcuts, collisions };
}

/**
 * Build the canonical chord string for a keyboard event (single step).
 *
 * `mod` is the platform-primary modifier (Meta on macOS, Ctrl elsewhere).
 * `Shift` is folded into a bare printable key (e.g. `?` needs Shift on most
 * layouts, so we do not surface a redundant `shift+?`); with any other modifier
 * present, `Shift` is kept (so `Mod+Shift+L` normalizes correctly).
 */
export function chordFromEvent(event: KeyboardEvent): string {
  const isMac =
    typeof navigator !== "undefined" && /mac/i.test(navigator.platform ?? "");
  const primary = isMac ? event.metaKey : event.ctrlKey;
  const secondaryMeta = isMac ? event.ctrlKey : event.metaKey;
  const key = event.key.toLowerCase();
  const printable = key.length === 1;

  const parts: string[] = [];
  if (primary) parts.push("mod");
  if (secondaryMeta) parts.push(isMac ? "ctrl" : "meta");
  if (event.altKey) parts.push("alt");
  const hasOtherModifier = primary || secondaryMeta || event.altKey;
  if (event.shiftKey && (!printable || hasOtherModifier)) parts.push("shift");
  parts.push(key);

  return normalizeChord(parts.join("+"));
}

/**
 * Bind a set of shortcut declarations to the window for the lifetime of the
 * component, returning the built registry (memoized) so the shortcuts overlay
 * can list the unambiguous bindings grouped by area.
 *
 * Only single-step chords are dispatched here; sequence chords (`g then d`)
 * are still registered and listed but their runtime dispatch is out of scope
 * for the current UX surface.
 */
export function useKeyboardShortcuts(
  declarations: readonly ShortcutDeclaration[],
): ShortcutRegistry {
  const registry = useMemo(
    () => buildShortcutRegistry(declarations),
    [declarations],
  );

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      const chord = chordFromEvent(event);
      const match = registry.byChord.get(chord);
      if (match?.run) {
        event.preventDefault();
        match.run();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [registry]);

  return registry;
}
