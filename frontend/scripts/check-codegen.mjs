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
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { runPackageBin } from "./node-bin.mjs";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

// Runs the pinned generator directly with the current Node binary — see
// `node-bin.mjs` for why this must not shell out to `npx`.
const regenerated = runPackageBin("openapi-typescript", ["./openapi.json"], {
  cwd: frontendRoot,
});

const committed = readFileSync(
  resolve(frontendRoot, "src", "api", "schema.d.ts"),
  "utf-8",
);

// Compare content, not line endings. `.gitattributes` pins `eol=lf` so a fresh
// checkout is LF on every OS, but a checkout predating that rule (or one made
// with it disabled) can hold CRLF, which would otherwise report drift on every
// single line on Windows and send you chasing a schema problem that isn't there.
const normalize = (text) => text.replace(/\r\n/g, "\n").trim();

if (normalize(regenerated) !== normalize(committed)) {
  console.error(
    "Codegen drift detected: src/api/schema.d.ts is out of sync with openapi.json.\n" +
      "Run `npm run codegen` and commit the regenerated schema.",
  );
  process.exit(1);
}

console.log("Codegen check passed — schema.d.ts matches openapi.json.");
