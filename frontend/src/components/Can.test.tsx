import { describe, it, expect } from "vitest";
import { cleanup } from "@testing-library/react";
import fc from "fast-check";

import { Can } from "./Can";
import { can, type Permission } from "../auth/rbac";
import type { Role } from "../auth/token";
import { makeSession, renderWithSession } from "../test/renderWithSession";

const roleArb = fc.constantFrom<Role>("owner", "admin", "member", "viewer");
const permissionArb = fc.constantFrom<Permission>(
  "read",
  "run_agents",
  "ingest_documents",
  "manage_api_keys",
  "manage_integrations",
  "read_audit_log",
  "manage_members",
);

describe("components/Can — RBAC gate", () => {
  // Feature: agentforge-frontend, Property 3: Control visibility is a pure function of role and required permission
  it("Property 3: control visibility is a pure function of role and required permission", () => {
    fc.assert(
      fc.property(roleArb, permissionArb, (role, permission) => {
        const { queryByTestId } = renderWithSession(
          <Can permission={permission}>
            <span data-testid="gated-child">visible</span>
          </Can>,
          makeSession(role),
        );
        const present = queryByTestId("gated-child") !== null;
        expect(present).toBe(can(role, permission));
        cleanup();
      }),
      { numRuns: 200 },
    );
  });

  it("renders nothing when unauthenticated (no role)", () => {
    const { queryByTestId } = renderWithSession(
      <Can permission="read">
        <span data-testid="gated-child">visible</span>
      </Can>,
      makeSession(null),
    );
    expect(queryByTestId("gated-child")).toBeNull();
  });
});
