/**
 * `CommandPalette`: the ⌘K / Ctrl-K command menu (cmdk).
 *
 * Surfaces navigation destinations and actions, each **RBAC-gated** by the same
 * `can(role, permission)` used for the sidebar nav so the palette never offers
 * an action the Session Role cannot perform (Req 4.2–4.5). Fully
 * keyboard-operable and screen-reader labeled via cmdk/Radix semantics; focus
 * is trapped while open and restored on close.
 */
import { Command as CommandPrimitive } from "cmdk";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";

import { can } from "../../auth/rbac";
import { useSession } from "../../auth/useSession";
import { useCommandPalette, OPEN_ORG_SWITCHER_EVENT } from "../../hooks/useCommandPalette";
import { useTheme } from "../../hooks/useTheme";
import { buildCommands, type Command } from "./commands";

/** Group commands by their `group` heading, preserving first-seen order. */
function groupCommands(commands: Command[]): [string, Command[]][] {
  const groups = new Map<string, Command[]>();
  for (const command of commands) {
    const bucket = groups.get(command.group);
    if (bucket) bucket.push(command);
    else groups.set(command.group, [command]);
  }
  return Array.from(groups.entries());
}

export function CommandPalette(): JSX.Element {
  const { paletteOpen, closePalette, openShortcuts } = useCommandPalette();
  const { role } = useSession();
  const navigate = useNavigate();
  const { toggleTheme } = useTheme();

  const commands = useMemo(
    () =>
      buildCommands({
        navigate: (path) => navigate(path),
        toggleTheme,
        openShortcuts,
        switchOrg: () =>
          window.dispatchEvent(new CustomEvent(OPEN_ORG_SWITCHER_EVENT)),
      }),
    [navigate, toggleTheme, openShortcuts],
  );

  // RBAC gate: only surface commands the Session Role can perform.
  const permitted = useMemo(
    () =>
      commands.filter(
        (command) =>
          command.permission === null ||
          (role !== null && can(role, command.permission)),
      ),
    [commands, role],
  );

  const grouped = useMemo(() => groupCommands(permitted), [permitted]);

  function run(command: Command): void {
    closePalette();
    command.perform();
  }

  return (
    <CommandPrimitive.Dialog
      open={paletteOpen}
      onOpenChange={(open) => {
        if (!open) closePalette();
      }}
      label="Command palette"
      shouldFilter
      className="af-glass fixed left-1/2 top-[15vh] z-50 w-[92vw] max-w-xl -translate-x-1/2 overflow-hidden rounded-xl border border-border-strong shadow-elevation-4"
    >
      <CommandPrimitive.Input
        placeholder="Search commands…"
        aria-label="Search commands"
        className="w-full border-b border-border bg-transparent px-4 py-3 text-sm text-text outline-none placeholder:text-text-muted"
      />
      <CommandPrimitive.List className="max-h-[50vh] overflow-y-auto p-2">
        <CommandPrimitive.Empty className="px-3 py-6 text-center text-sm text-text-muted">
          No matching commands.
        </CommandPrimitive.Empty>
        {grouped.map(([heading, groupCmds]) => (
          <CommandPrimitive.Group
            key={heading}
            heading={heading}
            className="px-1 py-1 text-xs font-medium text-text-muted [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5"
          >
            {groupCmds.map((command) => {
              const Icon = command.icon;
              return (
                <CommandPrimitive.Item
                  key={command.id}
                  value={`${command.label} ${(command.keywords ?? []).join(" ")}`}
                  onSelect={() => run(command)}
                  data-testid={`command-${command.id}`}
                  className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm text-text aria-selected:bg-surface-raised"
                >
                  {Icon ? <Icon className="h-4 w-4 text-text-muted" aria-hidden="true" /> : null}
                  <span>{command.label}</span>
                </CommandPrimitive.Item>
              );
            })}
          </CommandPrimitive.Group>
        ))}
      </CommandPrimitive.List>
    </CommandPrimitive.Dialog>
  );
}
