import { describe, it, expect } from "vitest";
import fc from "fast-check";

import { decodeClaims, isExpired, type Claims, type Role } from "./token";

/** Encode a JS value as a JWT-style base64url segment. */
function b64url(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Build a well-formed JWT (header.payload.signature) from a payload object. */
function makeJwt(payload: unknown): string {
  const header = b64url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const body = b64url(JSON.stringify(payload));
  const sig = b64url("signature");
  return `${header}.${body}.${sig}`;
}

const roleArb = fc.constantFrom<Role>("owner", "admin", "member", "viewer");

const validClaimsArb: fc.Arbitrary<Claims> = fc.record({
  sub: fc.string(),
  org_id: fc.string(),
  role: roleArb,
  // Finite integer seconds; wide range including negatives.
  exp: fc.integer({ min: -(2 ** 31), max: 2 ** 31 }),
});

describe("auth/token — decodeClaims + isExpired", () => {
  // Feature: agentforge-frontend, Property 1: Claims decoding is total and correct
  it("Property 1: claims decoding is total and correct", () => {
    // Well-formed side: exact round-trip of all four claims.
    fc.assert(
      fc.property(validClaimsArb, (claims) => {
        const token = makeJwt(claims);
        const decoded = decodeClaims(token);
        expect(decoded).toEqual(claims);
      }),
      { numRuns: 200 },
    );

    // Total side: never throws, and returns null for malformed / missing /
    // mistyped tokens.
    fc.assert(
      fc.property(fc.anything(), (garbage) => {
        expect(() => decodeClaims(garbage as unknown)).not.toThrow();
      }),
      { numRuns: 200 },
    );

    // Arbitrary strings: never throw; if a value happens to decode it must be
    // a fully-valid Claims object.
    fc.assert(
      fc.property(fc.string(), (s) => {
        const result = decodeClaims(s);
        if (result !== null) {
          expect(typeof result.sub).toBe("string");
          expect(typeof result.org_id).toBe("string");
          expect(["owner", "admin", "member", "viewer"]).toContain(result.role);
          expect(Number.isFinite(result.exp)).toBe(true);
        }
      }),
      { numRuns: 200 },
    );

    // Missing / mistyped claims each yield null.
    fc.assert(
      fc.property(
        validClaimsArb,
        fc.constantFrom("sub", "org_id", "role", "exp"),
        (claims, dropped) => {
          const mutated: Record<string, unknown> = { ...claims };
          delete mutated[dropped];
          expect(decodeClaims(makeJwt(mutated))).toBeNull();
          // Mistype: set the field to a wrong-typed value.
          mutated[dropped] = dropped === "exp" ? "not-a-number" : 12345;
          expect(decodeClaims(makeJwt(mutated))).toBeNull();
        },
      ),
      { numRuns: 200 },
    );
  });

  // Feature: agentforge-frontend, Property 2: Session expiry is decided solely by exp vs. now
  it("Property 2: session expiry is decided solely by exp vs. now", () => {
    fc.assert(
      fc.property(
        validClaimsArb,
        fc.integer({ min: -(2 ** 31), max: 2 ** 31 }),
        (claims, now) => {
          expect(isExpired(claims, now)).toBe(claims.exp <= now);
        },
      ),
      { numRuns: 200 },
    );
  });

  it("rejects a role outside the allowed set", () => {
    expect(decodeClaims(makeJwt({ sub: "u", org_id: "o", role: "root", exp: 1 }))).toBeNull();
  });

  it("rejects a non-three-segment token", () => {
    expect(decodeClaims("aaa.bbb")).toBeNull();
    expect(decodeClaims("only-one-part")).toBeNull();
  });
});
