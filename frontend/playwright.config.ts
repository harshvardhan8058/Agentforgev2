import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright E2E configuration for the AgentForge console.
 *
 * The suite runs the REAL production build (`vite build` -> `vite preview`) in a
 * real browser, and mocks the Backend_API at the network layer via
 * `page.route(...)` (see `e2e/helpers.ts`). It is therefore fully deterministic
 * and **keyless** — no live backend, database, or credential is required — while
 * still exercising routing, the auth gate, RBAC-gated UI, data rendering, the
 * responsive shell, and accessibility in an actual browser.
 *
 * The app calls its API at `http://localhost:8000` (the build-time default when
 * `VITE_API_BASE_URL` is unset), which is cross-origin to the preview server, so
 * API interception never touches the app's own assets.
 */
const PORT = 4173;
const BASE_URL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  timeout: 30_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  // Build once, then serve the production bundle for the whole run.
  webServer: {
    command: `npm run build && npm run preview -- --port ${PORT} --strictPort`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
