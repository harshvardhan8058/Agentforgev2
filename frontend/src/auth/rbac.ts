/**
 * Client mirror of the backend RBAC map (`enterprise/rbac.py`).
 *
 * The role → permission sets nest strictly `viewer ⊆ member ⊆ admin ⊆ owner`
 * and every role grants `read` (Property 4). `can` is a pure lookup: it can
 * never grant more than the backend authorizes, so RBAC-gated UI is a pure
 * function of the Session Role (Property 3, via `Can`).
 */
import type { Role } from "./token";

/** A named capability derived from the Role, mirroring the backend permissions. */
export type Permission =
  | "read"
  | "run_agents"
  | "ingest_documents"
  | "manage_api_keys"
  | "manage_members";

// Built incrementally so the nesting is explicit and cannot silently drift,
// exactly mirroring `enterprise/rbac.py`:
//   viewer = {read}
//   member = viewer ∪ {run_agents, ingest_documents}
//   admin  = member ∪ {manage_api_keys}
//   owner  = admin  ∪ {manage_members}
const VIEWER: ReadonlySet<Permission> = new Set<Permission>(["read"]);
const MEMBER: ReadonlySet<Permission> = new Set<Permission>([
  ...VIEWER,
  "run_agents",
  "ingest_documents",
]);
const ADMIN: ReadonlySet<Permission> = new Set<Permission>([
  ...MEMBER,
  "manage_api_keys",
]);
const OWNER: ReadonlySet<Permission> = new Set<Permission>([
  ...ADMIN,
  "manage_members",
]);

/** The static role → permission map mirroring the backend. */
export const ROLE_PERMISSIONS: Record<Role, ReadonlySet<Permission>> = {
  viewer: VIEWER,
  member: MEMBER,
  admin: ADMIN,
  owner: OWNER,
};

/** Pure authorization decision: does `role` grant `permission`? */
export function can(role: Role, permission: Permission): boolean {
  return ROLE_PERMISSIONS[role].has(permission);
}
