/**
 * Org-identity display helpers.
 *
 * The Session only carries the tenant `org_id` (an opaque identifier — often a
 * UUID). These pure helpers derive a friendly, deterministic visual identity
 * (a monogram + a stable accent hue) from that id so the workspace reads as a
 * real place rather than a raw string. The full id is always preserved by
 * callers as the element's text/`title` — these helpers only decorate it.
 */

/** First alphanumeric character of the id, uppercased (fallback "?"). */
export function orgMonogram(orgId: string): string {
  const match = orgId.match(/[a-z0-9]/i);
  return (match?.[0] ?? "?").toUpperCase();
}

/**
 * A stable hue (0–359) derived from the id via a small FNV-style hash, so a
 * given org always renders the same accent across sessions and reloads.
 */
export function orgHue(orgId: string): number {
  let hash = 2166136261;
  for (let i = 0; i < orgId.length; i += 1) {
    hash ^= orgId.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return Math.abs(hash) % 360;
}

/** Inline style for a monogram chip: a soft tinted background + readable fg. */
export function orgMonogramStyle(orgId: string): {
  backgroundColor: string;
  color: string;
} {
  const hue = orgHue(orgId);
  return {
    backgroundColor: `hsl(${hue} 70% 50% / 0.18)`,
    color: `hsl(${hue} 70% 62%)`,
  };
}
