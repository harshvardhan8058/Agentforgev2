/**
 * `ShortcutsOverlay`: the `?`-triggered keyboard-shortcuts help (Radix Dialog).
 *
 * Lists the built registry's unambiguous bindings grouped by area, rendering
 * each normalized chord as a sequence of `<kbd>` keys. Focus trapping, Escape
 * to close, and focus restoration are inherited from the Radix Dialog.
 */
import type { JSX } from "react";
import { Dialog, DialogContent } from "../ui/Dialog";
import { useCommandPalette } from "../../hooks/useCommandPalette";
import type { ResolvedShortcut } from "../../hooks/useKeyboardShortcuts";

/** Split a normalized chord into display key tokens. */
function chordKeys(chord: string): string[] {
  return chord
    .split(/\s+then\s+|\+/)
    .map((k) => k.trim())
    .filter(Boolean);
}

/** Group shortcuts by their declared area, preserving first-seen order. */
function groupByArea(
  shortcuts: readonly ResolvedShortcut[],
): [string, ResolvedShortcut[]][] {
  const groups = new Map<string, ResolvedShortcut[]>();
  for (const shortcut of shortcuts) {
    const bucket = groups.get(shortcut.area);
    if (bucket) bucket.push(shortcut);
    else groups.set(shortcut.area, [shortcut]);
  }
  return Array.from(groups.entries());
}

export function ShortcutsOverlay({
  shortcuts,
}: {
  shortcuts: readonly ResolvedShortcut[];
}): JSX.Element {
  const { shortcutsOpen, closeShortcuts } = useCommandPalette();
  const grouped = groupByArea(shortcuts);

  return (
    <Dialog
      open={shortcutsOpen}
      onOpenChange={(open) => {
        if (!open) closeShortcuts();
      }}
    >
      <DialogContent
        title="Keyboard shortcuts"
        description="Speed up your workflow with these key chords."
        data-testid="shortcuts-overlay"
      >
        <div className="flex flex-col gap-5" data-testid="shortcuts-overlay-body">
          {grouped.map(([area, areaShortcuts]) => (
            <section key={area} className="flex flex-col gap-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
                {area}
              </h3>
              <ul className="flex flex-col gap-1.5">
                {areaShortcuts.map((shortcut) => (
                  <li
                    key={shortcut.id}
                    className="flex items-center justify-between gap-4 text-sm text-text"
                  >
                    <span>{shortcut.label}</span>
                    <span className="flex items-center gap-1">
                      {chordKeys(shortcut.normalized).map((key, index) => (
                        <kbd
                          key={`${shortcut.id}-${index}`}
                          className="rounded border border-border bg-surface-raised px-1.5 py-0.5 text-xs font-medium text-text-muted"
                        >
                          {key}
                        </kbd>
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
