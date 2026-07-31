/**
 * `ConnectionConfigEditor`: a key/value editor for an integration's non-secret config.
 *
 * Integration connection config is a flat mapping of scalar settings, so the editor is a
 * list of key/value rows rather than a JSON text area: a text area would make a syntax
 * error the most likely failure, and would hide the shape the API actually accepts.
 *
 * Rows are held as an ordered array, not as an object, because an object cannot represent
 * a half-typed key without losing what the user has entered so far. `toConfig` collapses
 * them at submit time, dropping rows whose key is blank.
 *
 * The editor deliberately does **not** replicate the server's credential-shaped-key
 * policy. That rule lives in one place (`integrations/config_policy.py`) and its refusal
 * is surfaced verbatim; a second copy here would be a second thing to keep in sync. What
 * the editor does do is say plainly that credentials do not belong here.
 */
import type { JSX } from "react";
import { Plus, X } from "lucide-react";

import { Button } from "../../components/ui/Button";
import { Input } from "../../components/ui/Input";

/** A config value as the contract declares it. */
export type ConfigValue = string | number | boolean | null;

/**
 * One editable config entry.
 *
 * `id` is a stable React key across re-orders. `original` remembers the value as the server
 * sent it, together with the text it was rendered as: a text input can only hold a string,
 * so without that memory a round trip through the editor would rewrite every untouched
 * `notify: true` as the string `"true"` — silently changing the type of a value the user
 * never looked at, in a record that another system is expected to read.
 */
export interface ConfigRow {
  id: string;
  key: string;
  value: string;
  original?: { text: string; value: ConfigValue };
}

let rowCounter = 0;

/** Create an empty row with a stable identity. */
export function emptyRow(): ConfigRow {
  rowCounter += 1;
  return { id: `row-${rowCounter}`, key: "", value: "" };
}

/** Turn a stored config object into editable rows (stable order: as received). */
export function rowsFromConfig(config: Record<string, ConfigValue>): ConfigRow[] {
  const rows = Object.entries(config).map(([key, value]) => {
    // Scalars only, per the contract; null renders as an empty field. The original value
    // and its rendering are kept so an untouched row round-trips with its own type.
    const text = value === null || value === undefined ? "" : String(value);
    return { ...emptyRow(), key, value: text, original: { text, value: value ?? null } };
  });
  return rows.length > 0 ? rows : [emptyRow()];
}

/**
 * Collapse rows into the config object to submit.
 *
 * An **edited** value is sent as a string, which is what a text input holds: coercing "5"
 * to a number would be guesswork about a schema the server does not publish per integration,
 * and would change a legitimately string-valued setting. An **unedited** value is sent back
 * with the type it arrived with, because rewriting a boolean the user never touched is a
 * silent data change, not a formatting choice.
 */
export function toConfig(rows: readonly ConfigRow[]): Record<string, ConfigValue> {
  const config: Record<string, ConfigValue> = {};
  for (const row of rows) {
    const key = row.key.trim();
    if (key.length === 0) continue;
    config[key] =
      row.original !== undefined && row.original.text === row.value
        ? row.original.value
        : row.value;
  }
  return config;
}

export function ConnectionConfigEditor({
  rows,
  onChange,
  idPrefix,
}: {
  rows: readonly ConfigRow[];
  onChange: (rows: ConfigRow[]) => void;
  /** Prefix for input ids/test ids, so several editors can coexist on a page. */
  idPrefix: string;
}): JSX.Element {
  function update(id: string, patch: Partial<ConfigRow>): void {
    onChange(rows.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  }

  return (
    <div className="flex flex-col gap-2" data-testid={`${idPrefix}-editor`}>
      <div className="flex flex-col gap-2">
        {rows.map((row, index) => (
          <div key={row.id} className="flex flex-wrap items-center gap-2">
            <Input
              id={`${idPrefix}-key-${index}`}
              aria-label={`Setting name ${index + 1}`}
              data-testid={`${idPrefix}-key-${index}`}
              className="min-w-[9rem] flex-1"
              placeholder="default_channel"
              value={row.key}
              onChange={(e) => update(row.id, { key: e.target.value })}
            />
            <Input
              id={`${idPrefix}-value-${index}`}
              aria-label={`Setting value ${index + 1}`}
              data-testid={`${idPrefix}-value-${index}`}
              className="min-w-[9rem] flex-1"
              placeholder="#ops"
              value={row.value}
              onChange={(e) => update(row.id, { value: e.target.value })}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Remove setting ${index + 1}`}
              data-testid={`${idPrefix}-remove-${index}`}
              // Never leave zero rows: an empty editor offers nothing to type into.
              disabled={rows.length === 1}
              onClick={() => onChange(rows.filter((r) => r.id !== row.id))}
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        ))}
      </div>
      <div>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          data-testid={`${idPrefix}-add-row`}
          onClick={() => onChange([...rows, emptyRow()])}
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
          Add setting
        </Button>
      </div>
      <p className="text-xs text-text-muted">
        Non-secret settings only. Credentials are read from the server environment — a
        setting that looks like a token is refused.
      </p>
    </div>
  );
}
