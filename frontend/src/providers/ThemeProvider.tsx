/**
 * `ThemeProvider`: owns theme state, applies `data-theme` on `<html>`, and
 * persists explicit selections.
 *
 * It mirrors the pre-paint no-FOWT script in `index.html`: both read the same
 * `THEME_STORAGE_KEY` and the same `prefers-color-scheme` media query, so React
 * adopts the already-applied theme with no light→dark repaint. When no explicit
 * selection is stored, the provider honors the system preference and reacts to
 * live changes to it.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import type { ThemeName } from "../styles/theme";
import {
  ThemeContext,
  THEME_STORAGE_KEY,
  readStoredTheme,
  systemPreference,
  type ThemeApi,
} from "../hooks/useTheme";

/** Apply the theme to the document root (mirrors the pre-paint script). */
function applyTheme(theme: ThemeName): void {
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("data-theme", theme);
  }
}

export function ThemeProvider({ children }: { children: ReactNode }): JSX.Element {
  const [theme, setThemeState] = useState<ThemeName>(
    () => readStoredTheme() ?? systemPreference(),
  );
  // Whether the operator has made an explicit selection (vs. following system).
  const [explicit, setExplicit] = useState<boolean>(() => readStoredTheme() !== null);

  // Keep the DOM attribute in sync with state.
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // While following the system preference, react to live changes.
  useEffect(() => {
    if (explicit) return;
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const media = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = (): void => setThemeState(systemPreference());
    media.addEventListener?.("change", onChange);
    return () => media.removeEventListener?.("change", onChange);
  }, [explicit]);

  const setTheme = useCallback((next: ThemeName): void => {
    setExplicit(true);
    setThemeState(next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      /* persistence is best-effort; the in-memory theme still applies */
    }
  }, []);

  const toggleTheme = useCallback((): void => {
    setThemeState((current) => {
      const next: ThemeName = current === "dark" ? "light" : "dark";
      setExplicit(true);
      try {
        window.localStorage.setItem(THEME_STORAGE_KEY, next);
      } catch {
        /* best-effort */
      }
      return next;
    });
  }, []);

  const value = useMemo<ThemeApi>(
    () => ({ theme, setTheme, toggleTheme }),
    [theme, setTheme, toggleTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
