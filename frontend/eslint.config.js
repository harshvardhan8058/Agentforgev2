// ESLint 9 flat config for the AgentForge frontend.
//
// Layers, in order of increasing specificity:
//   1. global ignores (build output, generated code, test artifacts);
//   2. JS + typescript-eslint recommended (correctness baseline);
//   3. app source (src): browser globals + React Hooks rules + jsx-a11y
//      accessibility rules (the accessibility linter that guards WCAG-relevant
//      markup at author time);
//   4. tests + node tooling: relaxed environments/globals.
//
// tsc (noUnusedLocals/noUnusedParameters, strict) remains the source of truth
// for unused symbols; ESLint's no-unused-vars is aligned with an underscore
// escape hatch so the two never disagree.
import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import jsxA11y from "eslint-plugin-jsx-a11y";

export default tseslint.config(
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      "coverage/**",
      "playwright-report/**",
      "test-results/**",
      "src/api/schema.d.ts", // generated from openapi.json — never hand-edited
    ],
  },

  js.configs.recommended,
  ...tseslint.configs.recommended,

  // Application source: browser runtime + React + accessibility.
  {
    files: ["src/**/*.{ts,tsx}"],
    plugins: {
      "react-hooks": reactHooks,
      "jsx-a11y": jsxA11y,
    },
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.browser, ...globals.es2022 },
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...jsxA11y.flatConfigs.recommended.rules,
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", ignoreRestSiblings: true },
      ],
      // A horizontally scrollable container with no focusable content inside is
      // unreachable by keyboard — axe flags exactly that (`scrollable-region-focusable`,
      // WCAG 2.1.1) and the fix is `tabIndex={0}` on a labelled `role="region"`. The
      // rule's default allow-list stops at `tabpanel`, so it would otherwise forbid the
      // one remedy the accessibility scanner demands. Widened to those two roles only;
      // `tabIndex` on anything else stays an error.
      "jsx-a11y/no-noninteractive-tabindex": [
        "error",
        { tags: [], roles: ["tabpanel", "region"], allowExpressionValues: true },
      ],
    },
  },

  // Static browser bootstraps in public/ are deliberately external so the
  // deployment's strict `script-src 'self'` CSP can execute them.
  {
    files: ["public/**/*.js"],
    languageOptions: {
      globals: { ...globals.browser },
    },
  },

  // Tests + test helpers: add node + vitest globals, relax deliberate patterns.
  {
    files: [
      "src/**/*.{test,spec}.{ts,tsx}",
      "src/test/**/*.{ts,tsx}",
      "src/**/mocks/**/*.{ts,tsx}",
    ],
    languageOptions: {
      globals: { ...globals.node, ...globals.browser },
    },
    rules: {
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-empty-function": "off",
    },
  },

  // Node-side tooling (build/config/scripts).
  {
    files: ["*.config.{ts,js,mjs}", "scripts/**/*.{mjs,js,ts}", "e2e/**/*.{ts,mts}"],
    languageOptions: {
      globals: { ...globals.node },
    },
  },
);
