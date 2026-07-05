import { describe, it, expect } from "vitest";
import fc from "fast-check";

import { ROLE_PERMISSIONS, can, type Permission } from "./rbac";
import type { Role } from "./token";

const roleArb = fc.constantFrom<Role>("owner", "admin", "member", "viewer");
const permissionArb = fc.constantFrom<Permission>(
  "read",
  "run_agents",
  "ingest_documents",
  "manage_api_keys",
  "manage_members",
);

/** Subset check: every element of `a` is in `b`. */
function isSubset(a: ReadonlySet<Permission>, b: ReadonlySet<Permission>): boolean {
  for (const p of a) if (!b.has(p)) return false;
  return true;
}

describe("auth/rbac — ROLE_PERMISSIONS + can", () => {
  // Feature: agentforge-frontend, Property 4: The client RBAC map mirrors the backend nesting invariant
  it("Property 4: the client RBAC map mirrors the backend nesting invariant", () => {
    fc.assert(
      fc.property(roleArb, (role) => {
        // Every role grants `read`.
        expect(ROLE_PERMISSIONS[role].has("read")).toBe(true);
        expect(can(role, "read")).toBe(true);
      }),
      { numRuns: 200 },
    );

    // The nesting invariant viewer ⊆ member ⊆ admin ⊆ owner holds on every run.
    fc.assert(
      fc.property(fc.constant(null), () => {
        const { viewer, member, admin, owner } = ROLE_PERMISSIONS;
        expect(isSubset(viewer, member)).toBe(true);
        expect(isSubset(member, admin)).toBe(true);
        expect(isSubset(admin, owner)).toBe(true);
      }),
      { numRuns: 100 },
    );

    // `can` agrees with the map for every role × permission pair.
    fc.assert(
      fc.property(roleArb, permissionArb, (role, perm) => {
        expect(can(role, perm)).toBe(ROLE_PERMISSIONS[role].has(perm));
      }),
      { numRuns: 200 },
    );
  });

  it("mirrors the backend map exactly", () => {
    expect([...ROLE_PERMISSIONS.viewer].sort()).toEqual(["read"]);
    expect([...ROLE_PERMISSIONS.member].sort()).toEqual([
      "ingest_documents",
      "read",
      "run_agents",
    ]);
    expect([...ROLE_PERMISSIONS.admin].sort()).toEqual([
      "ingest_documents",
      "manage_api_keys",
      "read",
      "run_agents",
    ]);
    expect([...ROLE_PERMISSIONS.owner].sort()).toEqual([
      "ingest_documents",
      "manage_api_keys",
      "manage_members",
      "read",
      "run_agents",
    ]);
  });
});
