/**
 * A small store of known Access_Tokens keyed by `org_id`, backing the app-shell
 * **org switcher**.
 *
 * An Operator may hold tokens for multiple organizations; this module remembers
 * each valid token by its decoded `org_id` so switching organizations can
 * **adopt the stored token whose `org_id` matches the selection** (Req 4.6). It
 * is persisted (best-effort) to `localStorage` and never stores a token it
 * cannot decode.
 */
import { decodeClaims, type Role } from "./token";

const STORAGE_KEY = "agentforge.orgTokens";

/** A known organization the Operator holds a token for. */
export interface KnownOrg {
  orgId: string;
  role: Role;
  token: string;
}

// org_id -> raw token. `undefined` means "not yet hydrated".
let store: Map<string, string> | undefined;

function hydrate(): Map<string, string> {
  if (store !== undefined) return store;
  store = new Map<string, string>();
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        for (const [orgId, token] of Object.entries(parsed)) {
          if (typeof token === "string") store.set(orgId, token);
        }
      }
    }
  } catch {
    /* corrupt/unavailable storage — start empty */
  }
  return store;
}

function persist(): void {
  try {
    const obj: Record<string, string> = {};
    for (const [orgId, token] of hydrate()) obj[orgId] = token;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(obj));
  } catch {
    /* best-effort */
  }
}

/** Remember a token by its decoded `org_id`. No-op for undecodable tokens. */
export function rememberOrgToken(token: string): void {
  const claims = decodeClaims(token);
  if (claims === null) return;
  hydrate().set(claims.org_id, token);
  persist();
}

/** All organizations the Operator currently holds a decodable token for. */
export function listKnownOrgs(): KnownOrg[] {
  const orgs: KnownOrg[] = [];
  for (const [orgId, token] of hydrate()) {
    const claims = decodeClaims(token);
    if (claims !== null) {
      orgs.push({ orgId, role: claims.role, token });
    }
  }
  return orgs;
}

/** The stored token whose `org_id` matches `orgId`, or `null`. */
export function tokenForOrg(orgId: string): string | null {
  return hydrate().get(orgId) ?? null;
}

/** Test-only: reset the in-memory + persisted store. */
export function __resetOrgTokenStoreForTests(): void {
  store = undefined;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}
