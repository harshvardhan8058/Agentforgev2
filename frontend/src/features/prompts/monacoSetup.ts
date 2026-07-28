/**
 * Self-hosted Monaco bootstrap for the Prompt Studio.
 *
 * Why this module exists
 * ---------------------
 * `@monaco-editor/react` does **not** bundle Monaco. By default its loader injects a
 * `<script>` tag pointing at a public CDN (`https://cdn.jsdelivr.net/npm/monaco-editor@…`)
 * and pulls the editor down at runtime. That default is wrong for this app on three counts:
 *
 * 1. **It is blocked in the shipped stack.** The gateway sends a strict
 *    `Content-Security-Policy` with `script-src 'self'` (see
 *    `nginx/snippets/security_headers.conf`), so the CDN `<script>` is refused by the
 *    browser and the editor never mounts — the Prompt Studio silently renders an empty
 *    box in Docker/production while working fine under `vite dev`.
 * 2. **It breaks the keyless promise.** The platform claims zero external network calls
 *    without credentials; a third-party CDN fetch on the prompts route violates that and
 *    makes the console unusable in an air-gapped or egress-filtered deployment.
 * 3. **It is a supply-chain hole.** Editor code would be fetched from a third party at
 *    runtime, outside `package-lock.json`, unpinned by our integrity guarantees, and
 *    outside the bundle secret scan.
 *
 * Calling `loader.config({ monaco })` with a locally-installed `monaco-editor` makes the
 * loader resolve the instance we hand it instead of fetching anything, so the editor is
 * served same-origin from our own bundle.
 *
 * Scope of the import
 * -------------------
 * We import `editor.api` (the core editor) plus **only** the markdown language
 * contribution, rather than the `monaco-editor` barrel (`editor.main`) which registers
 * every bundled language and their workers. Prompt Studio edits markdown and diffs
 * markdown, so that is all we pay for. Diff computation lives in the core editor worker,
 * which is included here.
 *
 * This module is imported by `PromptStudio`, which is itself behind `React.lazy`, so none
 * of Monaco is in the initial bundle. `vite.config.ts` gives it a dedicated
 * `vendor-monaco` manual chunk to keep it out of the eager `vendor` chunk.
 */
// NOTE on specifiers: monaco-editor's package `exports` map is `"./*": "./esm/vs/*.js"`,
// so a subpath is written RELATIVE TO `esm/vs` — `monaco-editor/editor/editor.api`, not
// `monaco-editor/esm/vs/editor/editor.api` (which would resolve to `esm/vs/esm/vs/...`
// and fail).
import { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor/editor/editor.api";

// Markdown tokenization/colorization for the prompt body. Registering ONLY this language
// keeps the chunk far smaller than `basic-languages/monaco.contribution`, which registers
// every bundled language. The registration itself is tiny — it declares the language and a
// `loader` that dynamically imports the tokenizer, so the grammar is a separate lazy chunk.
import "monaco-editor/languages/definitions/markdown/register";

// The core editor worker backs model services and — importantly for the `diff` mode —
// diff computation. Vite compiles this to a same-origin asset, so it satisfies the
// gateway's `worker-src 'self'` and no CDN or blob worker is involved.
import EditorWorker from "monaco-editor/editor/editor.worker?worker";

/**
 * Wire the worker factory and hand our local Monaco to the loader.
 *
 * Idempotent: importing this module more than once (or re-mounting Prompt Studio) must not
 * reconfigure the loader, because `loader.config` is only honored before the first
 * `loader.init()` and re-running the assignment would be wasted work.
 */
let configured = false;

export function setupMonaco(): void {
  if (configured) return;
  configured = true;

  // Monaco discovers its workers through the global `MonacoEnvironment` hook. Returning a
  // worker instance directly (rather than a URL) avoids any cross-origin worker bootstrap.
  window.MonacoEnvironment = {
    getWorker() {
      return new EditorWorker();
    },
  };

  loader.config({ monaco });
}

setupMonaco();

export { monaco };
