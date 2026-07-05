/**
 * Type declarations for the bundle-secret scan script (consumed by the Vitest
 * test 27.1). The implementation lives in `scan-bundle-secrets.mjs` so it stays
 * runnable directly with `node` as a CLI.
 */
export interface SecretPattern {
  readonly name: string;
  readonly re: RegExp;
}

export interface SecretFinding {
  readonly pattern: string;
  readonly sample: string;
}

export interface DistFinding extends SecretFinding {
  readonly file: string;
}

export declare const SECRET_PATTERNS: readonly SecretPattern[];

export declare function collectBundleFiles(distDir: string): Promise<string[]>;
export declare function scanText(text: string): SecretFinding[];
export declare function scanDist(distDir: string): Promise<DistFinding[]>;
