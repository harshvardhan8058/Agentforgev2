/**
 * A small store of friendly organization **display names** keyed by `org_id`.
 *
 * The Access_Token only carries the opaque tenant `org_id` — never a name — so
 * the workspace would otherwise show a raw UUID everywhere. When an Operator
 * self-registers (or is otherwise known to name an org), we remember the chosen
 * name here, keyed by its `org_id`, so the shell, dashboard, and org switcher
 * can present a real name. It is persisted best-effort to `localStorage` and is
 * purely cosmetic — no name is ever required and the full id is always the
 * source of truth.
 */
import { shortOrgId } from "../lib/orgIdentity";

const STORAGE_KEY = "agentforge.orgNames";

// org_id -> friendly name. `undefined` means "not yet hydrated".
let store: Map<string, string> | undefined;

function hydrate(): Map<string, string> {
  if (store !== undefined) return store;
  store = new Map<string, string>();
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        for (const [orgId, name] of Object.entries(parsed)) {
          if (typeof name === "string") store.set(orgId, name);
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
    for (const [orgId, name] of hydrate()) obj[orgId] = name;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(obj));
  } catch {
    /* best-effort */
  }
}

/** Remember a friendly name for an org. Empty/blank names are ignored. */
export function rememberOrgName(orgId: string, name: string): void {
  const trimmed = name.trim();
  if (orgId.length === 0 || trimmed.length === 0) return;
  hydrate().set(orgId, trimmed);
  persist();
}

/** The remembered friendly name for an org, or `null` if none is known. */
export function getOrgName(orgId: string): string | null {
  const name = hydrate().get(orgId);
  return name && name.trim().length > 0 ? name : null;
}

/**
 * The best available display label for an org: its remembered friendly name
 * when known, otherwise a shortened form of the opaque id. Never empty.
 */
export function orgLabel(orgId: string): string {
  return getOrgName(orgId) ?? shortOrgId(orgId);
}

/** Test-only: reset the in-memory + persisted store. */
export function __resetOrgNameStoreForTests(): void {
  store = undefined;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}
