/**
 * Design-token TypeScript types + the pure `resolveToken(theme, role)` helper
 * (Property 13).
 *
 * The CSS custom properties in `tokens.css` are the runtime source of truth for
 * the visual layer; this module provides a *pure*, deterministic mirror of the
 * color semantic roles so token resolution is unit- and property-testable with
 * no DOM. `resolveToken` is **total**: it returns a defined, non-empty value for
 * every declared role in either theme, and a single deterministic fallback for
 * any undeclared role identifier — it never throws.
 */

/** The two shipped themes. Dark is the default. */
export type ThemeName = "dark" | "light";

/** The color semantic roles (not raw hues) the UI requests. */
export type SemanticRole =
  | "bg"
  | "bg-subtle"
  | "surface"
  | "surface-raised"
  | "surface-overlay"
  | "border"
  | "border-strong"
  | "text"
  | "text-muted"
  | "text-inverted"
  | "primary"
  | "primary-fg"
  | "accent"
  | "success"
  | "warning"
  | "danger"
  | "info"
  | "focus-ring"
  | "role-planner"
  | "role-researcher"
  | "role-writer"
  | "role-critic";

/**
 * The single deterministic fallback returned for any role identifier that is
 * not a declared `SemanticRole`. A stable neutral so an undeclared request can
 * never yield an undefined surface color or an empty string.
 */
export const FALLBACK_TOKEN = "#71717a" as const;

/**
 * Pure mirror of the color roles declared in `tokens.css`, per theme. Kept in
 * lock-step with the CSS custom properties so `resolveToken` and the rendered
 * UI agree.
 */
export const TOKENS: Record<ThemeName, Record<SemanticRole, string>> = {
  dark: {
    bg: "#0a0a0f",
    "bg-subtle": "#101018",
    surface: "#16161f",
    "surface-raised": "#1e1e2b",
    "surface-overlay": "rgba(24, 24, 34, 0.72)",
    border: "#2a2a38",
    "border-strong": "#3b3b50",
    text: "#f4f4fa",
    "text-muted": "#a2a2ba",
    "text-inverted": "#0a0a0f",
    primary: "#6366f1",
    "primary-fg": "#ffffff",
    accent: "#22d3ee",
    success: "#22c55e",
    warning: "#f59e0b",
    danger: "#ef4444",
    info: "#3b82f6",
    "focus-ring": "#818cf8",
    "role-planner": "#8b5cf6",
    "role-researcher": "#06b6d4",
    "role-writer": "#10b981",
    "role-critic": "#f43f5e",
  },
  light: {
    bg: "#f7f7fb",
    "bg-subtle": "#eeeef4",
    surface: "#ffffff",
    "surface-raised": "#ffffff",
    "surface-overlay": "rgba(255, 255, 255, 0.72)",
    border: "#e2e2ec",
    "border-strong": "#c7c7d6",
    text: "#14141c",
    "text-muted": "#55556a",
    "text-inverted": "#ffffff",
    primary: "#4f46e5",
    "primary-fg": "#ffffff",
    accent: "#0891b2",
    success: "#16a34a",
    warning: "#b45309",
    danger: "#dc2626",
    info: "#2563eb",
    "focus-ring": "#4f46e5",
    "role-planner": "#7c3aed",
    "role-researcher": "#0891b2",
    "role-writer": "#059669",
    "role-critic": "#e11d48",
  },
};

/** The declared semantic roles, exported for iteration/testing. */
export const SEMANTIC_ROLES: readonly SemanticRole[] = Object.keys(
  TOKENS.dark,
) as SemanticRole[];

/** Type guard: is `role` a declared `SemanticRole`? */
export function isSemanticRole(role: string): role is SemanticRole {
  return Object.prototype.hasOwnProperty.call(TOKENS.dark, role);
}

/**
 * Resolve a color token for `theme` × `role`.
 *
 * Total and deterministic (Property 13):
 *  - for any declared `SemanticRole`, returns that theme's defined, non-empty
 *    token value;
 *  - for any undeclared role identifier, returns the single deterministic
 *    `FALLBACK_TOKEN` (identical across repeated calls for the same input);
 *  - never throws.
 */
export function resolveToken(theme: ThemeName, role: string): string {
  const table = TOKENS[theme] ?? TOKENS.dark;
  if (isSemanticRole(role)) {
    return table[role];
  }
  return FALLBACK_TOKEN;
}

/** The corresponding CSS custom-property reference for a semantic role. */
export function tokenVar(role: SemanticRole): string {
  return `var(--color-${role})`;
}
