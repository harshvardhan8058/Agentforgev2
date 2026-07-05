/**
 * Codegen-drift check (Req 1.2, 1.3, Task 27).
 *
 * Regenerates the typed API surface from the committed backend OpenAPI schema
 * (`openapi.json`) and fails if the result differs from the committed
 * `src/api/schema.d.ts`. Wiring this into the CI/test scripts means any drift
 * between the client's types and the shipped contracts is caught at build time —
 * the client can never reference an endpoint or field the schema does not define
 * (that would additionally fail `tsc --noEmit`).
 *
 * Usage:
 *   node scripts/check-codegen.mjs      # exits 1 on drift
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const regenerated = execFileSync("npx", ["openapi-typescript", "./openapi.json"], {
  cwd: frontendRoot,
  encoding: "utf-8",
  stdio: ["ignore", "pipe", "inherit"],
});

const committed = readFileSync(
  resolve(frontendRoot, "src", "api", "schema.d.ts"),
  "utf-8",
);

if (regenerated.trim() !== committed.trim()) {
  console.error(
    "Codegen drift detected: src/api/schema.d.ts is out of sync with openapi.json.\n" +
      "Run `npm run codegen` and commit the regenerated schema.",
  );
  process.exit(1);
}

console.log("Codegen check passed — schema.d.ts matches openapi.json.");
