import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { BrowserRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import App from "./App";
import { resolveConfig } from "./config";
import { ThemeProvider } from "./providers/ThemeProvider";
import { ToastProvider } from "./providers/ToastProvider";
import { CommandPaletteProvider } from "./providers/CommandPaletteProvider";

/**
 * Task 1.1 — smoke test for scaffold, config, and the no-secret guarantee.
 * _Requirements: 1.1, 1.4, 1.5_
 */
describe("scaffold smoke test", () => {
  it("renders the app root", () => {
    const client = new QueryClient();
    render(
      <ThemeProvider>
        <ToastProvider>
          <CommandPaletteProvider>
            <QueryClientProvider client={client}>
              <BrowserRouter>
                <App />
              </BrowserRouter>
            </QueryClientProvider>
          </CommandPaletteProvider>
        </ToastProvider>
      </ThemeProvider>,
    );
    expect(screen.getByTestId("app-root")).toBeInTheDocument();
    // Unauthenticated by default → the public login view renders.
    expect(screen.getByTestId("login-view")).toBeInTheDocument();
  });

  it("resolves the base URL from import.meta.env.VITE_API_BASE_URL (Req 1.4)", () => {
    const cfg = resolveConfig({ VITE_API_BASE_URL: "https://api.example.test" });
    expect(cfg.baseUrl).toBe("https://api.example.test");
  });

  it("falls back to a default base URL when the env var is absent", () => {
    const cfg = resolveConfig({});
    expect(cfg.baseUrl).toBe("http://localhost:8000");
  });

  it("trims a trailing slash from the base URL", () => {
    const cfg = resolveConfig({ VITE_API_BASE_URL: "https://api.example.test/" });
    expect(cfg.baseUrl).toBe("https://api.example.test");
  });

  it("exposes only the base URL and non-secret flags — no secret fields (Req 1.5)", () => {
    const cfg = resolveConfig({ VITE_API_BASE_URL: "https://api.example.test" });
    // The config surface is exactly { baseUrl, flags }.
    expect(Object.keys(cfg).sort()).toEqual(["baseUrl", "flags"]);

    // A scan of the serialized config module must contain only the base URL /
    // non-secret flags and no credential-shaped material.
    const serialized = JSON.stringify(cfg).toLowerCase();
    for (const secretish of [
      "secret",
      "password",
      "token",
      "apikey",
      "api_key",
      "private",
      "credential",
    ]) {
      expect(serialized).not.toContain(secretish);
    }
  });
});
