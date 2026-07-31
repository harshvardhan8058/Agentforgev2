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
    // React.lazy in the router; the charts (Recharts) are dynamically imported
    // at their use site.
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          // Keep the React runtime and its router together with their low-level
          // transitive deps so no other vendor chunk forms a circular import
          // edge back into this one (Rollup rejects circular manual chunks).
          if (
            /[\\/]node_modules[\\/](react|react-dom|react-router|scheduler|loose-envify|js-tokens|object-assign|use-sync-external-store)[\\/]/.test(
              id,
            )
          ) {
            return "vendor-react";
          }
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
