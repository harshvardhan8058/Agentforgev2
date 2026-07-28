/**
 * `CommandPaletteProvider`: owns the global ⌘K palette and `?` shortcuts-overlay
 * open-state and exposes imperative controls via `useCommandPalette`.
 *
 * It holds **state only** so it can sit above the router in `main.tsx`; the
 * palette and overlay UI (which need router/session/theme context) are rendered
 * lower by `CommandLayer`, and the global key bindings are registered there too.
 */
import type { JSX } from "react";
import { useCallback, useMemo, useState, type ReactNode } from "react";

import {
  CommandPaletteContext,
  type CommandPaletteApi,
} from "../hooks/useCommandPalette";

export function CommandPaletteProvider({
  children,
}: {
  children: ReactNode;
}): JSX.Element {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);

  const openPalette = useCallback(() => setPaletteOpen(true), []);
  const closePalette = useCallback(() => setPaletteOpen(false), []);
  const togglePalette = useCallback(() => setPaletteOpen((o) => !o), []);
  const openShortcuts = useCallback(() => setShortcutsOpen(true), []);
  const closeShortcuts = useCallback(() => setShortcutsOpen(false), []);

  const value = useMemo<CommandPaletteApi>(
    () => ({
      paletteOpen,
      openPalette,
      closePalette,
      togglePalette,
      shortcutsOpen,
      openShortcuts,
      closeShortcuts,
    }),
    [
      paletteOpen,
      openPalette,
      closePalette,
      togglePalette,
      shortcutsOpen,
      openShortcuts,
      closeShortcuts,
    ],
  );

  return (
    <CommandPaletteContext.Provider value={value}>
      {children}
    </CommandPaletteContext.Provider>
  );
}
