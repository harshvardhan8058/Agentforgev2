import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Self-hosted fonts (subset latin woff2, font-display: swap via @fontsource).
// Bundled at build time — no network fetch at runtime.
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";

// Design tokens first, then the Tailwind global stylesheet that binds to them.
import "./styles/tokens.css";
import "./styles/globals.css";

import App from "./App";
import { ThemeProvider } from "./providers/ThemeProvider";
import { ToastProvider } from "./providers/ToastProvider";
import { CommandPaletteProvider } from "./providers/CommandPaletteProvider";

/**
 * React root + provider shell.
 *
 * Establishes the two cross-cutting providers the whole app depends on:
 *  - React Router v6 (`BrowserRouter`) for SPA routing.
 *  - TanStack Query v5 (`QueryClientProvider`) for server-state caching.
 *
 * No feature routes and no auth/session provider are mounted yet — those arrive
 * in later tasks. Additional providers (Session, Theme, Toast, CommandPalette)
 * will nest inside this shell.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
    },
  },
});

const rootElement = document.getElementById("root");
if (rootElement) {
  ReactDOM.createRoot(rootElement).render(
    <React.StrictMode>
      <ThemeProvider>
        <ToastProvider>
          <CommandPaletteProvider>
            <QueryClientProvider client={queryClient}>
              <BrowserRouter
                future={{
                  v7_startTransition: true,
                  v7_relativeSplatPath: true,
                }}
              >
                <App />
              </BrowserRouter>
            </QueryClientProvider>
          </CommandPaletteProvider>
        </ToastProvider>
      </ThemeProvider>
    </React.StrictMode>,
  );
}
