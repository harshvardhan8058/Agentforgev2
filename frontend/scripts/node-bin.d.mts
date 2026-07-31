/**
 * Type declarations for the cross-platform dependency-CLI runner. The
 * implementation lives in `node-bin.mjs` so it stays usable from plain `node`
 * scripts as well as from Vitest tests.
 */
export interface RunPackageBinOptions {
  /** Working directory for the child process. */
  readonly cwd?: string;
  /** Full environment for the child process. */
  readonly env?: Record<string, string | undefined>;
  /** How to treat the child's stdout. Defaults to `"pipe"`. */
  readonly stdout?: "pipe" | "ignore";
  /** How to treat the child's stderr. Defaults to `"inherit"`. */
  readonly stderr?: "inherit" | "ignore";
  /** Key in the package's `bin` map. Defaults to the package name. */
  readonly binName?: string;
}

export declare function resolvePackageBin(
  packageName: string,
  binName?: string,
): string;

export declare function runPackageBin(
  packageName: string,
  args: readonly string[],
  options?: RunPackageBinOptions,
): string;
