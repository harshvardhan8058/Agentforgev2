/**
 * `CommandLayer`: mounts the ⌘K palette + `?` shortcuts overlay and registers
 * the global key bindings.
 *
 * Rendered inside the router/session/theme context so the palette can navigate
 * and gate by Role. It builds the shortcut registry (`Mod+K`, `?`,
 * `Mod+Shift+L`) via the pure `useKeyboardShortcuts` builder and passes the
 * unambiguous bindings to the overlay.
 */
import type { JSX } from "react";
import { useMemo } from "react";

import { useCommandPalette } from "../../hooks/useCommandPalette";
import { useTheme } from "../../hooks/useTheme";
import {
  useKeyboardShortcuts,
  type ShortcutDeclaration,
} from "../../hooks/useKeyboardShortcuts";
import { CommandPalette } from "./CommandPalette";
import { ShortcutsOverlay } from "./ShortcutsOverlay";

export function CommandLayer(): JSX.Element {
  const { togglePalette, openShortcuts } = useCommandPalette();
  const { toggleTheme } = useTheme();

  const declarations = useMemo<ShortcutDeclaration[]>(
    () => [
      {
        id: "toggle-command-palette",
        chord: "Mod+K",
        label: "Open command palette",
        area: "General",
        run: togglePalette,
      },
      {
        id: "open-shortcuts-overlay",
        chord: "?",
        label: "Show keyboard shortcuts",
        area: "General",
        run: openShortcuts,
      },
      {
        id: "toggle-theme",
        chord: "Mod+Shift+L",
        label: "Toggle theme",
        area: "General",
        run: toggleTheme,
      },
    ],
    [togglePalette, openShortcuts, toggleTheme],
  );

  const registry = useKeyboardShortcuts(declarations);

  return (
    <>
      <CommandPalette />
      <ShortcutsOverlay shortcuts={registry.shortcuts} />
    </>
  );
}
