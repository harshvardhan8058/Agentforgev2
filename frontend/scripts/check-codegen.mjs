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
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/**
 * Resolve the generator from the installed devDependency and run it with the
 * current Node binary.
 *
 * This deliberately does NOT shell out to `npx`:
 *  - On Windows the executable is `npx.cmd`. `execFileSync` performs a direct
 *    CreateProcess with no shell, which cannot launch a `.cmd`, so the call dies
 *    with `spawnSync npx ENOENT`. The old form therefore only ever worked on
 *    Linux/macOS — which is exactly why CI stayed green while local Windows runs
 *    failed on the very first step of `npm run ci`.
 *  - Passing `shell: true` would "fix" that by handing the command line to
 *    cmd.exe, trading a portability bug for a quoting/injection surface.
 *  - `npx` can also fetch a *different* version of the generator than the pinned
 *    devDependency when local resolution misses, which would silently compare the
 *    committed schema against the output of the wrong generator.
 *
 * Resolving the real CLI path and invoking it via `process.execPath` avoids all
 * three: no shell, no PATH lookup, no `.cmd` shim, and the version is always the
 * one in the lockfile. `createRequire().resolve` (rather than a hardcoded
 * `node_modules/...` path) keeps this correct under hoisting.
 */
const require = createRequire(import.meta.url);
const generatorPkgPath = require.resolve("openapi-typescript/package.json");
const generatorPkg = JSON.parse(readFileSync(generatorPkgPath, "utf-8"));
const generatorBin =
  typeof generatorPkg.bin === "string"
    ? generatorPkg.bin
    : generatorPkg.bin["openapi-typescript"];
const generatorCli = resolve(dirname(generatorPkgPath), generatorBin);

const regenerated = execFileSync(process.execPath, [generatorCli, "./openapi.json"], {
  cwd: frontendRoot,
  encoding: "utf-8",
  stdio: ["ignore", "pipe", "inherit"],
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
