/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite + React 18 + TypeScript SPA configuration.
// The Vitest test toolchain (jsdom + RTL + fast-check + MSW) is configured here
// so `vitest --run` uses the same resolution as the app build.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
  build: {
    // Split large third-party libraries into separate, long-term-cacheable
    // vendor chunks so the app entry stays lean and a dependency bump only
    // invalidates its own chunk. Route code is additionally split via
    // React.lazy in the router; the editor (Monaco) and charts (Recharts) are
    // dynamically imported at their use sites.
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks(id) {
          // Pin Vite's dynamic-import preload helper to the React vendor chunk, which the
          // entry already loads eagerly. The helper is a tiny virtual module that is NOT
          // under node_modules, so without this it falls through to Rollup's own chunk
          // assignment — and Rollup happily parked it inside `vendor-monaco`. Because the
          // entry needs the helper, that turned the 2.6 MB editor chunk into a static
          // dependency of the entry (complete with a `modulepreload` link), eagerly
          // downloading Monaco on every page load and defeating its React.lazy boundary.
          if (id.includes("vite/preload-helper")) return "vendor-react";
          if (!id.includes("node_modules")) return undefined;
          // Keep the React runtime and its router together with their low-level
          // transitive deps so no other vendor chunk forms a circular import
          // edge back into this one (Rollup rejects circular manual chunks).
          if (
            // React Router v7 consolidated `react-router-dom` and `@remix-run/router`
            // into the single `react-router` package, which is the only one installed.
            /[\\/]node_modules[\\/](react|react-dom|react-router|scheduler|loose-envify|js-tokens|object-assign|use-sync-external-store|set-cookie-parser|cookie|turbo-stream)[\\/]/.test(
              id,
            )
          ) {
            return "vendor-react";
          }
          // Monaco must get its OWN chunk. Without this branch it falls through to the
          // catch-all "vendor" chunk below, which the eager app entry imports — that
          // would drag the whole editor into the initial download and defeat the
          // React.lazy boundary around Prompt Studio. As a dedicated chunk it is only
          // fetched when the prompts route actually mounts.
          if (id.includes("monaco-editor")) return "vendor-monaco";
          if (id.includes("@radix-ui") || id.includes("cmdk")) return "vendor-radix";
          if (id.includes("@tanstack")) return "vendor-query";
          if (id.includes("framer-motion")) return "vendor-motion";
          if (id.includes("recharts") || id.includes("d3-") || id.includes("victory")) {
            return "vendor-charts";
          }
          if (
            id.includes("react-markdown") ||
            id.includes("rehype") ||
            id.includes("remark") ||
            id.includes("hast") ||
            id.includes("mdast") ||
            id.includes("micromark") ||
            id.includes("highlight.js") ||
            id.includes("lowlight") ||
            id.includes("unified") ||
            id.includes("unist") ||
            id.includes("vfile") ||
            id.includes("property-information") ||
            id.includes("character-entities") ||
            id.includes("decode-named-character-reference") ||
            id.includes("comma-separated-tokens") ||
            id.includes("space-separated-tokens") ||
            id.includes("web-namespaces") ||
            id.includes("html-void-elements") ||
            id.includes("longest-streak") ||
            id.includes("zwitch") ||
            id.includes("trim-lines") ||
            id.includes("devlop")
          ) {
            return "vendor-markdown";
          }
          if (id.includes("lucide-react")) return "vendor-icons";
          return "vendor";
        },
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
