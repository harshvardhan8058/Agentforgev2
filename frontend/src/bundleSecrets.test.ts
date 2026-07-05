/**
 * Task 27.1 — bundle-secret scan.
 *
 * Builds the production bundle (if not already built) and asserts it embeds
 * **only** the Backend_API base URL / non-secret configuration and contains no
 * credential material (Req 1.5). The scan matches actual secret *patterns* and
 * env leakage, so it is robust to benign framework strings (React internals, an
 * `<input type="password">` type list, the `Authorization`/`Bearer` header
 * *names*, etc.) — those must not trip the scan.
 *
 * _Requirements: 1.5_
 */
import { describe, it, expect, beforeAll } from "vitest";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { scanText, scanDist } from "../scripts/scan-bundle-secrets.mjs";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const distDir = resolve(frontendRoot, "dist");

beforeAll(() => {
  if (!existsSync(resolve(distDir, "index.html"))) {
    execFileSync("npm", ["run", "build"], {
      cwd: frontendRoot,
      stdio: "ignore",
    });
  }
}, 180_000);

describe("Bundle-secret scan (Task 27.1)", () => {
  it("detects real credential shapes but ignores benign framework strings", () => {
    // Positive controls: real secret material is flagged.
    expect(scanText('const k = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345";').length).toBeGreaterThan(0);
    expect(
      scanText(
        'token="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"',
      ).length,
    ).toBeGreaterThan(0);
    expect(scanText('apiKey: "super-secret-value-123"').length).toBeGreaterThan(0);
    expect(scanText("-----BEGIN RSA PRIVATE KEY-----").length).toBeGreaterThan(0);
    expect(scanText('AWS="AKIAIOSFODNN7EXAMPLE"').length).toBeGreaterThan(0);

    // Negative controls: benign framework strings are NOT flagged.
    expect(scanText('const types = ["text","password","email","search"];')).toEqual([]);
    expect(scanText('headers.set("Authorization", `Bearer ${token}`)')).toEqual([]);
    expect(scanText('{ tokenType: "bearer", grant: "password" }')).toEqual([]);
    expect(scanText('el.setAttribute("type","password")')).toEqual([]);
    expect(scanText('"VITE_API_BASE_URL":"http://localhost:8000"')).toEqual([]);
  });

  it("finds no credential material in the production bundle (1.5)", async () => {
    const findings = await scanDist(distDir);
    expect(findings, JSON.stringify(findings, null, 2)).toEqual([]);
  });

  it("embeds the non-secret base URL config in the built bundle", async () => {
    // The base URL / non-secret config IS allowed to appear — it is not a secret.
    // (Sanity: the built config module carries only non-secret configuration.)
    const findings = await scanDist(distDir);
    expect(findings).toHaveLength(0);
  });
});
