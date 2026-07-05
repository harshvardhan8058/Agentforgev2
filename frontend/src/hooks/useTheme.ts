/**
 * `useTheme` + the theme context type and shared constants.
 *
 * The theme selection is read/set/persisted under a single stable
 * `localStorage` key — the *same* key the pre-paint no-FOWT script in
 * `index.html` reads — and falls back to the system `prefers-color-scheme` when
 * no explicit selection is stored. The provider (`providers/ThemeProvider.tsx`)
 * owns the state and applies `data-theme` on `<html>`; this hook exposes it.
 */
import { createContext, useContext } from "react";

import type { ThemeName } from "../styles/theme";

/** The stable localStorage key shared with the index.html pre-paint script. */
export const THEME_STORAGE_KEY = "agentforge.theme";

/** The theme API exposed to components. */
export interface ThemeApi {
  /** The active, resolved theme currently applied to `<html>`. */
  theme: ThemeName;
  /** Explicitly select and persist a theme. */
  setTheme(theme: ThemeName): void;
  /** Toggle between dark and light (and persist the result). */
  toggleTheme(): void;
}

export const ThemeContext = createContext<ThemeApi | null>(null);

/** Access the active theme. Must be used within a `ThemeProvider`. */
export function useTheme(): ThemeApi {
  const ctx = useContext(ThemeContext);
  if (ctx === null) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return ctx;
}

/** Resolve the system preference, defaulting to dark when unavailable. */
export function systemPreference(): ThemeName {
  if (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function"
  ) {
    return window.matchMedia("(prefers-color-scheme: light)").matches
      ? "light"
      : "dark";
  }
  return "dark";
}

/** Read the persisted explicit selection, or `null` when none/invalid. */
export function readStoredTheme(): ThemeName | null {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : null;
  } catch {
    return null;
  }
}
