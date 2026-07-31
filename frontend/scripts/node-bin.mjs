/**
 * Cross-platform execution of a dependency's CLI.
 *
 * Every place that needed to run a tool used to shell out to `npm`/`npx`:
 *
 *     execFileSync("npx", ["openapi-typescript", "./openapi.json"], …)
 *
 * `execFileSync` launches the target directly with no shell. On Windows the
 * executables are `npm.cmd` / `npx.cmd`, which `CreateProcess` cannot run, so
 * every such call died with `spawnSync npx ENOENT` (or `spawnSync npm ENOENT`).
 * Those calls only ever worked on Linux/macOS, which is why CI stayed green
 * while `npm run ci` could not get past its first step on Windows.
 *
 * Two tempting alternatives were rejected:
 *  - `shell: true` fixes Windows by routing the command line through `cmd.exe`,
 *    trading a portability bug for a quoting/injection surface.
 *  - keeping `npx` risks it *fetching* a different version than the pinned
 *    devDependency when local resolution misses — a codegen-drift check that
 *    compares against the wrong generator is worse than no check at all.
 *
 * Resolving the CLI's real path and invoking it with `process.execPath` avoids
 * both: no shell, no PATH lookup, no `.cmd` shim, and the tool is always the
 * version in the lockfile. `createRequire().resolve` (rather than a hardcoded
 * `node_modules/…` path) keeps this correct under dependency hoisting.
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";

const require = createRequire(import.meta.url);

/**
 * Absolute path to the JS entrypoint of a dependency's bin.
 *
 * @param {string} packageName npm package that owns the CLI.
 * @param {string} [binName] Key in the package's `bin` map. Defaults to `packageName`.
 * @returns {string} Absolute path to the CLI's entry script.
 */
export function resolvePackageBin(packageName, binName = packageName) {
  const pkgPath = require.resolve(`${packageName}/package.json`);
  const pkg = JSON.parse(readFileSync(pkgPath, "utf-8"));
  const relative = typeof pkg.bin === "string" ? pkg.bin : pkg.bin?.[binName];
  if (!relative) {
    throw new Error(
      `Package "${packageName}" declares no bin entry "${binName}". ` +
        `Found: ${JSON.stringify(pkg.bin)}`,
    );
  }
  return resolve(dirname(pkgPath), relative);
}

/**
 * Run a dependency's CLI with the current Node binary and return its stdout.
 *
 * @param {string} packageName npm package that owns the CLI.
 * @param {string[]} args Arguments passed to the CLI.
 * @param {object} [options]
 * @param {string} [options.cwd] Working directory for the child process.
 * @param {Record<string, string | undefined>} [options.env] Full child environment.
 * @param {"pipe" | "ignore"} [options.stdout] How to treat stdout. Default `"pipe"`.
 * @param {"inherit" | "ignore"} [options.stderr] How to treat stderr. Default `"inherit"`.
 * @param {string} [options.binName] Key in the package's `bin` map.
 * @returns {string} The child's stdout, or `""` when stdout is ignored.
 */
export function runPackageBin(packageName, args, options = {}) {
  const {
    cwd,
    env,
    stdout = "pipe",
    stderr = "inherit",
    binName = packageName,
  } = options;
  const output = execFileSync(
    process.execPath,
    [resolvePackageBin(packageName, binName), ...args],
    {
      cwd,
      env,
      encoding: "utf-8",
      stdio: ["ignore", stdout, stderr],
    },
  );
  return output ?? "";
}
