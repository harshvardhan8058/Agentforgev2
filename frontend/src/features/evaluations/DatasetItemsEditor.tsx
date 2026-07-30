/**
 * `DatasetItemsEditor`: the input/expected rows that make up an evaluation
 * dataset.
 *
 * This exists because the create-dataset form previously sent `items: []`
 * unconditionally. The API accepts items and the framework scores *every item in
 * the dataset*, so an empty dataset produced no results and an aggregate of
 * exactly 0 — the whole Evaluations feature was inert, and nothing in the UI
 * explained why. There was no way to add an item at all.
 *
 * `expected` matters as much as `input`: `exact_match` and `contains` both score
 * 0 when `expected` is absent, so an item without an expectation can only ever
 * fail. The editor therefore treats `expected` as a first-class field and warns
 * when it is missing rather than silently sending null.
 */
import type { JSX } from "react";
import { Plus, Trash2 } from "lucide-react";

import { Button } from "../../components/ui/Button";
import { Input } from "../../components/ui/Input";
import { ExampleChips } from "../../components/ui/ExampleChips";
import { EVALUATION_ITEM_PRESETS } from "../../lib/examples";

/** A dataset item being edited. `expected` is optional per the API contract. */
export interface DraftItem {
  input: string;
  expected: string;
}

/** A blank row. */
export function emptyItem(): DraftItem {
  return { input: "", expected: "" };
}

/**
 * The items that will actually be sent: rows with a non-blank input.
 *
 * `input` has `min_length=1` server-side, so a blank row would be rejected as a
 * validation error for the whole request. A blank `expected` is sent as `null`,
 * matching the contract's optional field rather than an empty string.
 */
export function toRequestItems(
  items: readonly DraftItem[],
): { input: string; expected: string | null }[] {
  return items
    .filter((item) => item.input.trim().length > 0)
    .map((item) => ({
      input: item.input.trim(),
      expected: item.expected.trim().length > 0 ? item.expected.trim() : null,
    }));
}

export function DatasetItemsEditor({
  items,
  onChange,
}: {
  items: readonly DraftItem[];
  onChange: (next: DraftItem[]) => void;
}): JSX.Element {
  const usable = toRequestItems(items);
  const missingExpected = usable.filter((item) => item.expected === null).length;

  function update(index: number, patch: Partial<DraftItem>): void {
    onChange(items.map((item, i) => (i === index ? { ...item, ...patch } : item)));
  }

  return (
    <div className="flex flex-col gap-2" data-testid="dataset-items-editor">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-medium text-text">Items</span>
        <span className="text-xs text-text-subtle" data-testid="dataset-item-count">
          {usable.length} will be saved
        </span>
      </div>

      <p className="text-xs leading-relaxed text-text-muted">
        Each item is a question and the answer you expect. A run sends every input
        through the pipeline and scores the result against your expectation.
      </p>

      <ExampleChips
        label="Load a set"
        examples={EVALUATION_ITEM_PRESETS.map((preset) => ({
          label: preset.label,
          value: preset.label,
        }))}
        onPick={(label) => {
          const preset = EVALUATION_ITEM_PRESETS.find((p) => p.label === label);
          if (preset) onChange(preset.items.map((item) => ({ ...item })));
        }}
        testId="dataset-item-presets"
      />

      <ul className="flex flex-col gap-2" data-testid="dataset-item-rows">
        {items.map((item, index) => (
          <li
            key={index}
            className="flex flex-col gap-2 rounded-lg border border-border bg-bg-subtle p-2"
            data-testid={`dataset-item-${index}`}
          >
            <div className="flex items-center gap-2">
              <label
                className="w-16 shrink-0 text-xs text-text-muted"
                htmlFor={`dataset-item-input-${index}`}
              >
                Input
              </label>
              <Input
                id={`dataset-item-input-${index}`}
                data-testid={`dataset-item-input-${index}`}
                value={item.input}
                onChange={(e) => update(index, { input: e.target.value })}
                placeholder="What does onboarding provide on day one?"
                className="h-9"
              />
            </div>
            <div className="flex items-center gap-2">
              <label
                className="w-16 shrink-0 text-xs text-text-muted"
                htmlFor={`dataset-item-expected-${index}`}
              >
                Expected
              </label>
              <Input
                id={`dataset-item-expected-${index}`}
                data-testid={`dataset-item-expected-${index}`}
                value={item.expected}
                onChange={(e) => update(index, { expected: e.target.value })}
                placeholder="A laptop, a display, and a headset"
                className="h-9"
              />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={`Remove item ${index + 1}`}
                data-testid={`dataset-item-remove-${index}`}
                // Always leave one row: an editor with no rows offers no way back.
                disabled={items.length <= 1}
                onClick={() => onChange(items.filter((_, i) => i !== index))}
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          </li>
        ))}
      </ul>

      <div>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          data-testid="dataset-item-add"
          onClick={() => onChange([...items, emptyItem()])}
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
          Add item
        </Button>
      </div>

      {usable.length === 0 && (
        <p className="text-xs text-warning" data-testid="dataset-items-empty-warning">
          Add at least one item — a run over an empty dataset scores nothing.
        </p>
      )}
      {missingExpected > 0 && (
        <p className="text-xs text-warning" data-testid="dataset-items-expected-warning">
          {missingExpected} item{missingExpected === 1 ? "" : "s"} have no expected
          answer. exact_match and contains always score 0 without one.
        </p>
      )}
    </div>
  );
}
