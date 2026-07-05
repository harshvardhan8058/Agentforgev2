/**
 * Pure JWT claims decoding + expiry — the leaf of the Session layer.
 *
 * `decodeClaims` is **total**: for ANY string it returns a fully-typed `Claims`
 * for a well-formed JWT whose payload carries all four correctly-typed claims,
 * and `null` for anything malformed, undecodable, or missing/mistyping a
 * required claim. It never throws (Property 1). `isExpired` is a pure
 * comparison of `exp` against a supplied `nowSeconds` (Property 2).
 *
 * No network, no credentials, no side effects — this module is unit- and
 * property-tested in isolation.
 */

/** The four RBAC roles carried in the Access_Token, nested viewer ⊆ … ⊆ owner. */
export type Role = "owner" | "admin" | "member" | "viewer";

const ROLES: ReadonlySet<string> = new Set<Role>([
  "owner",
  "admin",
  "member",
  "viewer",
]);

/** The decoded, validated Access_Token payload the Session is derived from. */
export interface Claims {
  sub: string;
  org_id: string;
  role: Role;
  /** Seconds since the epoch. */
  exp: number;
}

/**
 * Decode a base64url string to its UTF-8 text, or return `null` on any failure.
 * Uses the platform `atob`; pads and normalizes the base64url alphabet first.
 */
function base64UrlDecode(segment: string): string | null {
  try {
    // Reject anything outside the base64url alphabet.
    if (!/^[A-Za-z0-9_-]*$/.test(segment)) {
      return null;
    }
    const normalized = segment.replace(/-/g, "+").replace(/_/g, "/");
    const padLength = (4 - (normalized.length % 4)) % 4;
    const padded = normalized + "=".repeat(padLength);
    const binary = atob(padded);
    // Decode the binary string as UTF-8.
    const bytes = Uint8Array.from(binary, (ch) => ch.charCodeAt(0));
    return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
  } catch {
    return null;
  }
}

/** A payload is a plain (non-array, non-null) object. */
function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Decode a JWT payload into `Claims`.
 *
 * Returns `null` (never throws) for any token that is malformed, undecodable,
 * or whose payload is missing or mistypes any of `sub`, `org_id`, `role`, `exp`.
 */
export function decodeClaims(token: unknown): Claims | null {
  if (typeof token !== "string") {
    return null;
  }
  const parts = token.split(".");
  // A JWT is header.payload.signature — exactly three segments.
  if (parts.length !== 3) {
    return null;
  }
  const payloadText = base64UrlDecode(parts[1]);
  if (payloadText === null) {
    return null;
  }

  let payload: unknown;
  try {
    payload = JSON.parse(payloadText);
  } catch {
    return null;
  }
  if (!isPlainObject(payload)) {
    return null;
  }

  const { sub, org_id, role, exp } = payload;
  if (typeof sub !== "string") return null;
  if (typeof org_id !== "string") return null;
  if (typeof role !== "string" || !ROLES.has(role)) return null;
  // `exp` must be a finite number (seconds). Reject NaN/Infinity and non-numbers.
  if (typeof exp !== "number" || !Number.isFinite(exp)) return null;

  return { sub, org_id, role: role as Role, exp };
}

/** True iff the token is expired at `nowSeconds` — i.e. `exp <= now`. */
export function isExpired(claims: Claims, nowSeconds: number): boolean {
  return claims.exp <= nowSeconds;
}
