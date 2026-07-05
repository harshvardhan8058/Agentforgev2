import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import App from "./App";

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
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </React.StrictMode>,
  );
}
