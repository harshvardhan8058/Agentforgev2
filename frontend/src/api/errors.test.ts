import { describe, it, expect } from "vitest";
import fc from "fast-check";

import { mapError } from "./errors";

const statusArb = fc.oneof(
  fc.constant<number | null>(null),
  fc.integer({ min: 100, max: 599 }),
  fc.constantFrom(400, 401, 403, 404, 409, 413, 415, 422, 429, 500, 502),
);

const envelopeArb = fc.record({
  error: fc.record({
    code: fc.string(),
    message: fc.string({ minLength: 1 }),
    details: fc.dictionary(fc.string(), fc.anything()),
  }),
});

const bodyArb = fc.oneof(
  envelopeArb,
  fc.anything(), // garbage / partial
  fc.constant(undefined),
  fc.constant(null),
);

describe("api/errors — mapError", () => {
  // Feature: agentforge-frontend, Property 5: Error-envelope normalization is total
  it("Property 5: error-envelope normalization is total", () => {
    fc.assert(
      fc.property(statusArb, bodyArb, (status, body) => {
        let result;
        expect(() => {
          result = mapError(status, body);
        }).not.toThrow();
        const err = result!;
        // Always a non-empty, user-presentable message.
        expect(typeof err.message).toBe("string");
        expect(err.message.length).toBeGreaterThan(0);
        expect(typeof err.code).toBe("string");
        expect(err.code.length).toBeGreaterThan(0);
        expect(err.status).toBe(status);
        expect(typeof err.details).toBe("object");
        // Network case.
        if (status === null) {
          expect(err.kind).toBe("network");
        }
        // 500 never surfaces stack-trace-like text.
        if (status === 500) {
          expect(err.kind).toBe("server");
          expect(err.message.toLowerCase()).not.toContain("traceback");
          expect(err.message).not.toContain("    at ");
        }
      }),
      { numRuns: 300 },
    );
  });

  it("copies code/message/details verbatim from a valid envelope", () => {
    const body = {
      error: { code: "guardrail_blocked", message: "blocked here", details: { reason: "policy" } },
    };
    const err = mapError(400, body);
    expect(err.code).toBe("guardrail_blocked");
    expect(err.message).toBe("blocked here");
    expect(err.details).toEqual({ reason: "policy" });
    expect(err.kind).toBe("validation");
  });

  it("maps 422 validation_error to fieldErrors", () => {
    const body = {
      error: {
        code: "validation_error",
        message: "Request validation failed.",
        details: {
          errors: [
            { loc: ["body", "email"], msg: "field required" },
            { loc: ["body", "password"], msg: "too short" },
          ],
        },
      },
    };
    const err = mapError(422, body);
    expect(err.kind).toBe("validation");
    expect(err.fieldErrors).toEqual({ email: "field required", password: "too short" });
  });

  it("does not leak another org for a cross-tenant 404", () => {
    const body = { error: { code: "not_found", message: "Resource not found.", details: {} } };
    const err = mapError(404, body);
    expect(err.kind).toBe("not_found");
    expect(err.message.toLowerCase()).not.toContain("org");
    expect(err.message.toLowerCase()).not.toContain("tenant");
  });

  it("produces kind=network with null status", () => {
    const err = mapError(null, undefined);
    expect(err.kind).toBe("network");
    expect(err.code).toBe("network");
    expect(err.message.length).toBeGreaterThan(0);
  });
});
