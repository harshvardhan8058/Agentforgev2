/**
 * `useCommandPalette` + the palette/overlay context type.
 *
 * The `CommandPaletteProvider` owns the global ⌘K palette open-state and the
 * `?` shortcuts-overlay open-state; this hook exposes imperative controls to
 * open/close/toggle each, so any surface (a button, a command, a shortcut) can
 * drive them.
 */
import { createContext, useContext } from "react";

/** Imperative controls for the command palette + shortcuts overlay. */
export interface CommandPaletteApi {
  paletteOpen: boolean;
  openPalette(): void;
  closePalette(): void;
  togglePalette(): void;
  shortcutsOpen: boolean;
  openShortcuts(): void;
  closeShortcuts(): void;
}

export const CommandPaletteContext = createContext<CommandPaletteApi | null>(null);

/** Access the command-palette controls. Must be used within its provider. */
export function useCommandPalette(): CommandPaletteApi {
  const ctx = useContext(CommandPaletteContext);
  if (ctx === null) {
    throw new Error(
      "useCommandPalette must be used within a CommandPaletteProvider",
    );
  }
  return ctx;
}

/** Window event the "Switch organization" command dispatches for the shell. */
export const OPEN_ORG_SWITCHER_EVENT = "agentforge:open-org-switcher";
