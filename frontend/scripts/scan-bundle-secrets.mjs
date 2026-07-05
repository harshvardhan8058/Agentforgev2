/**
 * Bundle-secret scan (Req 1.5, Task 27 / 27.1).
 *
 * Asserts that the production build embeds **only** the Backend_API base URL and
 * non-secret configuration — never any credential material. The Web_Client
 * obtains its Access_Token at runtime via the login flow; no secret is ever read
 * by `config.ts` or compiled into the bundle.
 *
 * The scan matches **actual secret patterns and env leakage** — token/key
 * shapes and `secret = "…"`-style assignments — rather than the mere presence of
 * a word like "password" or "token", so it does not false-positive on benign
 * framework strings (React internals, an `<input type="password">` type list,
 * `Authorization`/`Bearer` header *names*, etc.).
 *
 * Usage:
 *   node scripts/scan-bundle-secrets.mjs [distDir]   # exits 1 on any finding
 *
 * Also exports pure helpers (`scanText`, `scanDist`, `collectBundleFiles`) that
 * the Vitest test (27.1) imports directly.
 */
import { readdir, readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join, extname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

/**
 * Secret / credential *patterns* — shapes that only real secret material takes.
 * Each entry names the class of leak it detects.
 */
export const SECRET_PATTERNS = [
  // JWT (three base64url segments). A leaked Access_Token would look like this.
  { name: "jwt", re: /eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/ },
  // Provider API keys.
  { name: "openai-or-anthropic-key", re: /\bsk-(?:proj-|ant-)?[A-Za-z0-9]{20,}\b/ },
  { name: "aws-access-key-id", re: /\bAKIA[0-9A-Z]{16}\b/ },
  { name: "google-api-key", re: /\bAIza[0-9A-Za-z_-]{35}\b/ },
  { name: "slack-token", re: /\bxox[baprs]-[0-9A-Za-z-]{10,}\b/ },
  { name: "github-token", re: /\bgh[pousr]_[A-Za-z0-9]{20,}\b/ },
  { name: "stripe-secret-key", re: /\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}\b/ },
  // PEM private-key blocks.
  { name: "private-key-block", re: /-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----/ },
  // A secret-bearing key assigned a non-trivial literal value (env leakage).
  {
    name: "secret-assignment",
    re: /\b(?:secret|password|passwd|api[_-]?key|access[_-]?key|secret[_-]?key|client[_-]?secret|private[_-]?key|refresh[_-]?token|auth[_-]?token)\b\s*[:=]\s*["'`][^"'`\n]{8,}["'`]/i,
  },
  // A concrete bearer token literal (header *value*, not the header name).
  { name: "bearer-token-literal", re: /Bearer\s+eyJ[A-Za-z0-9_-]{8,}/ },
  // A leaked secret-bearing VITE_ env var baked into the bundle.
  {
    name: "vite-secret-env",
    re: /VITE_[A-Z0-9_]*(?:SECRET|PASSWORD|API_?KEY|ACCESS_?KEY|TOKEN|PRIVATE)[A-Z0-9_]*\s*[:=]\s*["'`][^"'`\n]{4,}["'`]/,
  },
];

const SCANNED_EXTENSIONS = new Set([".js", ".mjs", ".cjs", ".css", ".html", ".map"]);

/** Recursively collect the built asset files worth scanning. */
export async function collectBundleFiles(distDir) {
  const out = [];
  async function walk(dir) {
    const entries = await readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        await walk(full);
      } else if (SCANNED_EXTENSIONS.has(extname(entry.name).toLowerCase())) {
        out.push(full);
      }
    }
  }
  await walk(distDir);
  return out.sort();
}

/** Scan a single text blob, returning any secret findings (pure). */
export function scanText(text) {
  const findings = [];
  for (const { name, re } of SECRET_PATTERNS) {
    const match = text.match(re);
    if (match) {
      findings.push({
        pattern: name,
        // Keep only a short, redacted excerpt so the report never leaks a secret.
        sample: `${match[0].slice(0, 8)}…`,
      });
    }
  }
  return findings;
}

/** Scan every built asset under `distDir`, returning findings with file paths. */
export async function scanDist(distDir) {
  if (!existsSync(distDir)) {
    throw new Error(`dist directory not found: ${distDir} (run \`npm run build\` first)`);
  }
  const files = await collectBundleFiles(distDir);
  const findings = [];
  for (const file of files) {
    const text = await readFile(file, "utf-8");
    for (const f of scanText(text)) findings.push({ file, ...f });
  }
  return findings;
}

// CLI entry point.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const distDir = process.argv[2] ?? fileURLToPath(new URL("../dist", import.meta.url));
  scanDist(distDir)
    .then((findings) => {
      if (findings.length > 0) {
        console.error(`Bundle-secret scan FAILED — ${findings.length} finding(s):`);
        for (const f of findings) {
          console.error(`  • [${f.pattern}] ${f.sample} in ${f.file}`);
        }
        process.exit(1);
      }
      console.log(`Bundle-secret scan passed — no credential material found in ${distDir}.`);
    })
    .catch((err) => {
      console.error(String(err));
      process.exit(2);
    });
}
